import json
import logging
from dataclasses import asdict
from email.utils import formataddr, parseaddr
from os import environ
from time import time
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from urllib import error as urllib_error
from urllib import request as urllib_request

from channels.consumer import SyncConsumer
from django.conf import settings
from django.core import mail
from django.template import Context, Template
from html2text import html2text

from draw.models import Debate
from participants.models import Person
from tournaments.models import Round, Tournament

from .models import BulkNotification, EmailStatus, SentMessage
from .utils import (AdjudicatorAssignmentEmailGenerator, BallotsEmailGenerator, MotionReleaseEmailGenerator,
                    NotificationContextGenerator, RandomizedUrlEmailGenerator, StandingsEmailGenerator,
                    TeamDrawEmailGenerator, TeamSpeakerEmailGenerator)


logger = logging.getLogger(__name__)


class NotificationQueueConsumer(SyncConsumer):

    NOTIFICATION_GENERATORS: Dict[BulkNotification.EventType, Type[NotificationContextGenerator]] = {
        BulkNotification.EventType.ADJ_DRAW: AdjudicatorAssignmentEmailGenerator,
        BulkNotification.EventType.URL: RandomizedUrlEmailGenerator,
        BulkNotification.EventType.BALLOTS_CONFIRMED: BallotsEmailGenerator,
        BulkNotification.EventType.POINTS: StandingsEmailGenerator,
        BulkNotification.EventType.MOTIONS: MotionReleaseEmailGenerator,
        BulkNotification.EventType.TEAM_REG: TeamSpeakerEmailGenerator,
        BulkNotification.EventType.TEAM_DRAW: TeamDrawEmailGenerator,
        BulkNotification.EventType.CUSTOM: NotificationContextGenerator,
    }

    @staticmethod
    def _send(messages: List[mail.EmailMultiAlternatives], records: List[SentMessage]) -> None:
        SentMessage.objects.bulk_create(records)

        zepto_token = environ.get('ZEPTO_SEND_MAIL_TOKEN', '').strip()
        if zepto_token:
            NotificationQueueConsumer._send_zeptomail(messages, records, zepto_token)
            return

        connection = mail.get_connection(fail_silently=False)
        failed_events = []

        connection.open()
        for message, record in zip(messages, records):
            try:
                message.extra_headers['X-RECORDID'] = record.id
                connection.send_messages([message])
            except Exception as e:
                failed_events.append(EmailStatus(email=record, event=EmailStatus.EventType.FAILED, data={'error': str(e)}))
        connection.close()

        EmailStatus.objects.bulk_create(failed_events)

    @staticmethod
    def _parsed_email(value: str) -> Dict[str, str]:
        name, address = parseaddr(value)
        if not address:
            raise ValueError(f"invalid email address: {value!r}")
        result = {'address': address}
        if name:
            result['name'] = name
        return result

    @staticmethod
    def _bool_env(name: str, default: bool = False) -> bool:
        raw = environ.get(name, '').strip().lower()
        if not raw:
            return default
        return raw in ('1', 'true', 'yes', 'on')

    @staticmethod
    def _message_html_body(message: mail.EmailMultiAlternatives) -> Optional[str]:
        for content, mimetype in message.alternatives:
            if mimetype == 'text/html':
                return content
        return None

    @staticmethod
    def _zeptomail_authorization(token: str) -> str:
        return token if token.lower().startswith('zoho-enczapikey ') else f'Zoho-enczapikey {token}'

    @staticmethod
    def _send_smtp_fallback(message: mail.EmailMultiAlternatives, record: SentMessage, provider_data: Dict[str, Any]) -> EmailStatus:
        try:
            message.extra_headers['X-RECORDID'] = record.id
            connection = mail.get_connection(fail_silently=False)
            connection.open()
            try:
                connection.send_messages([message])
            finally:
                connection.close()
            return EmailStatus(
                email=record,
                event=EmailStatus.EventType.PROCESSED,
                data={'provider': 'zeptomail-smtp-fallback', 'zeptomail': provider_data},
            )
        except Exception as e:
            logger.exception(
                "ZeptoMail SMTP fallback failed: subject=%r from=%r to=%r hook_id=%s",
                message.subject, message.from_email, message.to, record.hook_id,
            )
            return EmailStatus(
                email=record,
                event=EmailStatus.EventType.FAILED,
                data={'provider': 'zeptomail-smtp-fallback', 'zeptomail': provider_data, 'smtp_error': str(e)},
            )

    @staticmethod
    def _send_zeptomail(messages: List[mail.EmailMultiAlternatives], records: List[SentMessage], token: str) -> None:
        api_url = environ.get('ZEPTO_API_URL', 'https://api.zeptomail.com/v1.1/email').strip()
        org_slug = environ.get("YELLOWTABS_ORG_SLUG", "").strip().lower()
        statuses = []

        for message, record in zip(messages, records):
            try:
                headers = dict(message.extra_headers or {})
                payload = {
                    'from': NotificationQueueConsumer._parsed_email(message.from_email),
                    'to': [{'email_address': NotificationQueueConsumer._parsed_email(addr)} for addr in message.to],
                    'subject': message.subject,
                    'client_reference': f'{org_slug}:{record.hook_id}' if org_slug else record.hook_id,
                    'track_opens': NotificationQueueConsumer._bool_env('ZEPTO_TRACK_OPENS', False),
                    'track_clicks': NotificationQueueConsumer._bool_env('ZEPTO_TRACK_CLICKS', False),
                    'mime_headers': headers,
                }
                html_body = NotificationQueueConsumer._message_html_body(message)
                if html_body:
                    payload['htmlbody'] = html_body
                else:
                    payload['textbody'] = message.body
                if message.reply_to:
                    payload['reply_to'] = [NotificationQueueConsumer._parsed_email(addr) for addr in message.reply_to]

                body = json.dumps(payload).encode('utf-8')
                req = urllib_request.Request(
                    api_url,
                    data=body,
                    method='POST',
                    headers={
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                        'Authorization': NotificationQueueConsumer._zeptomail_authorization(token),
                    },
                )
                with urllib_request.urlopen(req, timeout=15) as response:
                    response_body = response.read().decode('utf-8')
                try:
                    response_data = json.loads(response_body) if response_body else {}
                except ValueError:
                    response_data = {'raw': response_body}
                statuses.append(EmailStatus(
                    email=record,
                    event=EmailStatus.EventType.PROCESSED,
                    data={'provider': 'zeptomail', 'response': response_data},
                ))
            except urllib_error.HTTPError as e:
                error_body = e.read().decode('utf-8', errors='replace')
                logger.error(
                    "ZeptoMail send failed: status=%s subject=%r from=%r to=%r hook_id=%s response=%s",
                    e.code, message.subject, message.from_email, message.to, record.hook_id, error_body,
                )
                if 500 <= e.code <= 599:
                    statuses.append(NotificationQueueConsumer._send_smtp_fallback(
                        message, record, {'status': e.code, 'error': error_body},
                    ))
                    continue
                statuses.append(EmailStatus(
                    email=record,
                    event=EmailStatus.EventType.FAILED,
                    data={'provider': 'zeptomail', 'status': e.code, 'error': error_body},
                ))
            except urllib_error.URLError as e:
                logger.exception(
                    "ZeptoMail send failed before HTTP response: subject=%r from=%r to=%r hook_id=%s",
                    message.subject, message.from_email, message.to, record.hook_id,
                )
                statuses.append(NotificationQueueConsumer._send_smtp_fallback(
                    message, record, {'error': str(e)},
                ))
            except Exception as e:
                logger.exception(
                    "ZeptoMail send failed before response: subject=%r from=%r to=%r hook_id=%s",
                    message.subject, message.from_email, message.to, record.hook_id,
                )
                statuses.append(EmailStatus(
                    email=record,
                    event=EmailStatus.EventType.FAILED,
                    data={'provider': 'zeptomail', 'error': str(e)},
                ))

        EmailStatus.objects.bulk_create(statuses)

    @staticmethod
    def _get_from_fields(t: Tournament) -> Tuple[str, Optional[List[str]]]:
        notification_from_email = getattr(settings, 'YELLOWTABS_NOTIFICATION_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL)
        from_email = formataddr((t.short_name, notification_from_email))
        if t.pref('reply_to_address'):
            return from_email, [formataddr((t.pref('reply_to_name').strip(), t.pref('reply_to_address')))]
        return from_email, None  # Shouldn't have array of None

    @staticmethod
    def _tracking_headers(t: Tournament, hook_id: str) -> Dict[str, str]:
        if environ.get('ZEPTO_SEND_MAIL_TOKEN', '').strip():
            return {
                'X-YT-Hook-ID': hook_id,
                'X-YT-Org-Slug': environ.get("YELLOWTABS_ORG_SLUG", "").strip().lower(),
                'X-YT-Tournament-Slug': t.slug,
            }
        configuration_set = environ.get('YELLOWTABS_SES_CONFIGURATION_SET', '').strip()
        if configuration_set:
            return {
                'X-SES-CONFIGURATION-SET': configuration_set,
                'X-SES-MESSAGE-TAGS': (
                    f'hook_id={hook_id}, '
                    f'yt_org_slug={environ.get("YELLOWTABS_ORG_SLUG", "").strip().lower()}, '
                    f'yt_tournament_slug={t.slug}'
                ),
            }
        return {
            'X-SMTPAPI': json.dumps({'unique_args': {'hook-id': hook_id}}),  # Legacy SendGrid-specific fallback
        }

    def email(self, event: Dict[str, Union[str, BulkNotification.EventType, List[int], Dict[str, Any]]]) -> None:
        # Get database objects
        if 'debate_id' in event['extra']:
            debate = Debate.objects.select_related('round__tournament').get(pk=event['extra'].pop('debate_id'))
            event['extra']['debate'] = debate
            round = event['extra']['debate'].round
            t = round.tournament
        elif 'round_id' in event['extra']:
            round = Round.objects.select_related('tournament').get(pk=event['extra'].pop('round_id'))
            event['extra']['round'] = round
            t = round.tournament
        else:
            round = None
            t = Tournament.objects.get(pk=event['extra'].pop('tournament_id'))
            event['extra']['tournament'] = t

        from_email, reply_to = self._get_from_fields(t)
        notification_type = event['message']

        subject = Template(event['subject'])
        html_body = Template(event['body'])

        recipients = Person.objects.filter(pk__in=event['send_to'] or [], email__isnull=False).exclude(email='')
        contexts = self.NOTIFICATION_GENERATORS[notification_type].generate(to=recipients, **event['extra'])

        # Prepare messages

        # Ballot receipts are grouped by round in the same BulkNotification
        creation_kwargs = {
            'round': round,
            'tournament': t,
            'subject_template': event['subject'],
            'body_template': event['body'],
        }
        if notification_type is BulkNotification.EventType.BALLOTS_CONFIRMED:
            bulk_notification, c = BulkNotification.objects.get_or_create(
                event=BulkNotification.EventType.BALLOTS_CONFIRMED, **creation_kwargs)
        else:
            bulk_notification = BulkNotification.objects.create(event=notification_type, **creation_kwargs)

        messages = []
        records = []
        for instance, recipient in contexts:
            data = asdict(instance)
            data['USER'] = recipient.name

            hook_id = str(bulk_notification.id) + "-" + str(recipient.id) + "-" + str(int(time()))[4:]
            context = Context(data)
            body = html_body.render(context)
            email = mail.EmailMultiAlternatives(
                subject=subject.render(context), body=html2text(body),
                from_email=from_email, to=[formataddr((recipient.name.strip(), recipient.email))],
                reply_to=reply_to, headers=self._tracking_headers(t, hook_id),
            )
            email.attach_alternative(body, "text/html")
            messages.append(email)

            raw_message = email.message()
            records.append(
                SentMessage(recipient=recipient, email=recipient.email,
                            method=SentMessage.METHOD_TYPE_EMAIL,
                            context=data, message_id=raw_message['Message-ID'],
                            hook_id=hook_id, notification=bulk_notification))

        self._send(messages, records)
