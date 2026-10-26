"""
Wallet balance computation and on-demand reward verification.

Balance model
-------------
earned_balance  — freely available (withdraw only)
ad_wallet       — advertising funds (campaign payments / refunds)
hold_balance    — locked funds (campaign budgets + rewards in hold window)

Rewards are credited to hold_balance first. After the hold window clears
(and membership is confirmed), funds move hold → earned_balance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.campaigns.models import Campaign, CampaignParticipation
from apps.rewards.models import RewardTransaction
from apps.users.models import TelegramUser
from apps.users.utils import is_user_in_channel

MIN_WITHDRAW_AMOUNT = Decimal(str(getattr(settings, 'MIN_WITHDRAW_AMOUNT', '20')))


@dataclass
class WalletSnapshot:
    earned_balance: Decimal
    ad_wallet: Decimal
    hold_balance: Decimal
    total_earned: Decimal
    total_transactions: int


def _release_hold_to_wallet(user: TelegramUser, amount: Decimal) -> None:
    """Move cleared reward funds from hold into the spendable wallet."""
    amount = Decimal(amount)
    # Cap to current hold so legacy rows (credited to wallet before hold_balance)
    # are marked complete without double-crediting.
    release = min(amount, max(Decimal('0'), user.hold_balance))
    if release <= 0:
        return
    user.hold_balance -= release
    user.earned_balance += release
    user.save(update_fields=['hold_balance', 'earned_balance'])


def _deduct_held_reward(user: TelegramUser, amount: Decimal) -> None:
    """Remove a clawed-back reward, preferring hold then earned_balance (legacy-safe)."""
    amount = Decimal(amount)
    from_hold = min(amount, max(Decimal('0'), user.hold_balance))
    remainder = amount - from_hold 
    if remainder > 0:
        user.earned_balance = max(Decimal('0'), user.earned_balance - remainder)
    else:
        user.hold_balance -= from_hold
    user.save(update_fields=['hold_balance', 'earned_balance'])


def _return_reward_to_campaign(campaign: Campaign, amount: Decimal) -> None:
    """Return a clawed-back reward to the campaign owner / budget."""
    amount = Decimal(amount)
    owner = TelegramUser.objects.select_for_update().get(pk=campaign.owner_id)

    if campaign.status in (Campaign.Status.COMPLETED, Campaign.Status.CANCELED):
        owner.ad_wallet += amount
        owner.save(update_fields=['ad_wallet'])
    else:
        campaign.budget_spent = max(Decimal('0'), campaign.budget_spent - amount)
        owner.hold_balance += amount
        owner.save(update_fields=['hold_balance'])

    campaign.current_participants = max(0, campaign.current_participants - 1)
    campaign.save()


def _clawback_referral_reward(user: TelegramUser, tx: RewardTransaction) -> None:
    """Revoke a referral reward held for the promoter."""
    _deduct_held_reward(user, tx.amount)
    tx.status = RewardTransaction.Status.REVOKED
    tx.description += ' (Verification: referred member not in channel)'

    if tx.campaign:
        _return_reward_to_campaign(tx.campaign, tx.amount)

    tx.save(update_fields=['status', 'description'])


def _clawback_task_reward(user: TelegramUser, tx: RewardTransaction) -> None:
    """Revoke a task reward still inside its verification window."""
    _deduct_held_reward(user, tx.amount)
    tx.status = RewardTransaction.Status.REVOKED
    tx.expires_at = None
    tx.description += ' (Verification: user not in channel)'

    campaign = tx.campaign
    if campaign:
        participation = CampaignParticipation.objects.filter(
            user=user,
            campaign=campaign,
        ).first()
        if participation:
            participation.status = CampaignParticipation.Status.REJECTED
            participation.save(update_fields=['status'])

        _return_reward_to_campaign(campaign, tx.amount)

    tx.save(update_fields=['status', 'description', 'expires_at'])


def _member_still_in_channel(tx: RewardTransaction, user: TelegramUser) -> bool:
    if not tx.campaign:
        return False
    member_id = tx.member_telegram_id or user.telegram_id
    return is_user_in_channel(tx.campaign.channel_id, member_id)


def verify_rewards_on_demand(user: TelegramUser) -> None:
    """
    Verify rewards that are still in (or just passed) their hold window:
    - Pending referral rewards: release hold→wallet after expiry, or claw back.
    - Completed task rewards: release hold→wallet if still in channel, else claw back.
    """
    now = timezone.now()
    user_id = user.pk

    expired_pending = RewardTransaction.objects.select_for_update().filter(
        user_id=user_id,
        status=RewardTransaction.Status.PENDING,
        tx_type=RewardTransaction.TxType.REFERRAL_REWARD,
        expires_at__lt=now,
    ).select_related('campaign', 'campaign__owner')

    for tx in expired_pending:
        if _member_still_in_channel(tx, user):
            tx.status = RewardTransaction.Status.COMPLETED
            tx.save(update_fields=['status'])
            _release_hold_to_wallet(user, tx.amount)
        else:
            _clawback_referral_reward(user, tx)

    active_pending = RewardTransaction.objects.select_for_update().filter(
        user_id=user_id,
        status=RewardTransaction.Status.PENDING,
        tx_type=RewardTransaction.TxType.REFERRAL_REWARD,
        expires_at__gte=now,
    ).select_related('campaign', 'campaign__owner')

    for tx in active_pending:
        if tx.campaign and not _member_still_in_channel(tx, user):
            _clawback_referral_reward(user, tx)

    # Task rewards with an active hold marker (expires_at set):
    # while the window is open, claw back if the user left; after it ends, release hold → wallet.
    # Clearing expires_at marks the reward as fully released (no double-credit).
    held_tasks = RewardTransaction.objects.select_for_update().filter(
        user_id=user_id,
        status=RewardTransaction.Status.COMPLETED,
        tx_type=RewardTransaction.TxType.TASK_REWARD,
        expires_at__isnull=False,
    ).select_related('campaign', 'campaign__owner')

    for tx in held_tasks:
        if tx.expires_at >= now:
            if tx.campaign and not _member_still_in_channel(tx, user):
                _clawback_task_reward(user, tx)
            continue

        tx.expires_at = None
        tx.save(update_fields=['expires_at'])
        _release_hold_to_wallet(user, tx.amount)


def compute_wallet_snapshot(user: TelegramUser) -> WalletSnapshot:
    stats = RewardTransaction.objects.filter(
        user=user,
        tx_type__in=[
            RewardTransaction.TxType.TASK_REWARD,
            RewardTransaction.TxType.REFERRAL_REWARD,
        ],
        status=RewardTransaction.Status.COMPLETED,
    ).aggregate(
        total_earned=Sum('amount'),
        total_transactions=Count('id'),
    )

    return WalletSnapshot(
        earned_balance=user.earned_balance,
        ad_wallet=user.ad_wallet,
        hold_balance=max(Decimal('0'), user.hold_balance),
        total_earned=stats['total_earned'] or Decimal('0'),
        total_transactions=stats['total_transactions'] or 0,
    )


@transaction.atomic
def prepare_wallet_for_withdraw(user: TelegramUser) -> WalletSnapshot:
    """Lock the user row, run verification, and return up-to-date balances."""
    locked_user = TelegramUser.objects.select_for_update().get(pk=user.pk)
    verify_rewards_on_demand(locked_user)
    locked_user.refresh_from_db(fields=['earned_balance', 'ad_wallet', 'hold_balance'])
    return compute_wallet_snapshot(locked_user)
