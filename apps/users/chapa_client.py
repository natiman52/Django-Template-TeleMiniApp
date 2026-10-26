"""
Chapa REST API helpers for verifying payments and transfers.
"""

from __future__ import annotations

import logging
from typing import Optional
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SUCCESS_STATUSES = frozenset({'success', 'successful', 'completed', 'paid'})
FAILED_STATUSES = frozenset({'failed', 'failure', 'cancelled', 'canceled', 'reversed', 'declined'})
PENDING_STATUSES = frozenset({'pending', 'processing', 'initiated', 'new', 'ongoing'})


def _chapa_secret_key() -> str:
    return (
        getattr(settings, 'CHAPA_SECRET_KEY', '')
        or getattr(settings, 'CHAPA_KEY', '')
    )


def _normalize_status(raw_status: Optional[str]) -> Optional[str]:
    if not raw_status:
        return None
    status = raw_status.strip().lower()
    if status in SUCCESS_STATUSES:
        return 'success'
    if status in FAILED_STATUSES:
        return 'failed'
    if status in PENDING_STATUSES:
        return 'pending'
    return status


def _extract_status(payload: dict) -> Optional[str]:
    data = payload.get('data')
    if isinstance(data, dict):
        for key in ('status', 'transfer_status', 'payment_status'):
            if data.get(key):
                return _normalize_status(str(data[key]))
    return _normalize_status(str(payload.get('status', '')))


def verify_chapa_transfer(reference: str) -> tuple[Optional[str], str]:
    """
    Verify a Chapa bank transfer by reference.
    Returns (normalized_status, message) where status is success|failed|pending or None on error.
    """
    secret_key = _chapa_secret_key()
    if not secret_key:
        return None, 'Chapa secret key is not configured.'

    try:
        response = requests.get(
            f'https://api.chapa.co/v1/transfers/verify/{reference}',
            headers={'Authorization': f'Bearer {secret_key}'},
            timeout=15,
        )
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning('Chapa transfer verify failed for %s: %s', reference, exc)
        return None, str(exc)
    except ValueError:
        return None, 'Invalid JSON response from Chapa transfer verify API.'

    message = str(payload.get('message', ''))
    if response.status_code >= 400:
        return None, message or f'Chapa API error ({response.status_code})'

    return _extract_status(payload), message


def verify_chapa_payment(tx_ref: str) -> tuple[Optional[str], str]:
    """
    Verify a Chapa payment (deposit) by tx_ref.
    Returns (normalized_status, message) where status is success|failed|pending or None on error.
    """
    secret_key = _chapa_secret_key()
    if not secret_key:
        return None, 'Chapa secret key is not configured.'

    try:
        response = requests.get(
            f'https://api.chapa.co/v1/transaction/verify/{tx_ref}',
            headers={'Authorization': f'Bearer {secret_key}'},
            timeout=15,
        )
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning('Chapa payment verify failed for %s: %s', tx_ref, exc)
        return None, str(exc)
    except ValueError:
        return None, 'Invalid JSON response from Chapa payment verify API.'

    message = str(payload.get('message', ''))
    if response.status_code >= 400:
        top_status = _normalize_status(str(payload.get('status', '')))
        if top_status == 'failed':
            return 'failed', message or 'Payment verification failed.'
        return None, message or f'Chapa API error ({response.status_code})'

    return _extract_status(payload), message


def create_chapa_checkout_url(
    *,
    amount: float,
    first_name: str,
    last_name: str,
    tx_ref: str,
    callback_url: str,
    return_url: str,
    description: str = '',
) -> tuple[Optional[str], str]:
    """
    Creates a Chapa checkout URL for direct payment.
    Returns (checkout_url, error_message) where checkout_url is the Chapa payment page URL or None on error.
    """
    secret_key = _chapa_secret_key()
    if not secret_key:
        return None, 'Chapa secret key is not configured.'
    
    try:
        response = requests.post(
            'https://api.chapa.co/v1/transaction/initialize',
            headers={'Authorization': f'Bearer {secret_key}'},
            json={
                'amount': str(amount),
                'currency': 'ETB',
                'first_name': first_name,
                'last_name': last_name,
                'tx_ref': tx_ref,
                'callback_url': callback_url,
                'return_url': return_url,
                'customization[title]': 'Campaign Payment',
                'customization[description]': description[:200],
            },
            timeout=15,
        )
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning('Chapa checkout creation failed: %s', exc)
        return None, str(exc)
    except ValueError:
        return None, 'Invalid JSON response from Chapa checkout API.'
    
    if response.status_code >= 400:
        message = str(payload.get('message', ''))
        top_status = _normalize_status(str(payload.get('status', '')))
        if top_status == 'failed':
            return None, message or 'Chapa checkout creation failed.'
        return None, message or f'Chapa API error ({response.status_code})'
    
    checkout_url = payload.get('data', {}).get('checkout_url')
    if not checkout_url:
        return None, 'No checkout URL returned from Chapa.'
    
    return checkout_url, ''
