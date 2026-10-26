from django.db import models

# Create your models here.
from django.db import models
from django.db.models import TextChoices


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True, primary_key=True)
    username = models.CharField(max_length=64, blank=True, null=True)
    first_name = models.CharField(max_length=64, blank=True, default='')
    last_name = models.CharField(max_length=64, blank=True, default='')
    guided = models.BooleanField(default=False)
    photo_url = models.URLField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)
    earned_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    ad_wallet = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    hold_balance = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    admin = models.BooleanField(default=False)
    platform_referred_users = models.ManyToManyField(
        'self',
        through='referrals.PlatformReferral',
        through_fields=('referrer', 'referred'),
        symmetrical=False,
        related_name='referred_by_platform',
        blank=True,
    )

    class Meta:
        db_table = 'telegram_users'

    @property
    def display_name(self):
        if self.username:
            return f'@{self.username}'
        return f'{self.first_name} {self.last_name}'.strip() or str(self.telegram_id)

    def __str__(self):
        return self.display_name


class BotNotification(models.Model):
    """Queue for outgoing Telegram bot messages with retry support."""

    class Status(TextChoices):
        PENDING = 'pending', 'Pending'
        SENT    = 'sent',    'Sent'
        FAILED  = 'failed',  'Failed'

    user       = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='bot_notifications',
    )
    message    = models.TextField()
    status     = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    retries    = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bot_notifications'
        ordering = ['created_at']

    def __str__(self):
        return f'[{self.status}] → {self.user} ({self.created_at:%Y-%m-%d %H:%M})'
