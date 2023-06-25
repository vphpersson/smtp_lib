from typing import Final
from re import Pattern as RePattern, compile as re_compile
from dataclasses import dataclass

from ecs_py import SMTPExchange, SMTPRequest, SMTPResponse, SMTPEnhancedStatusCode

from smtp_lib.codes import CLASS_TO_TEXT, SUBJECT_TO_TEXT, SUBJECT_DETAIL_TO_TEXT


_SMTP_RESPONSE_PATTERN: Final[RePattern] = re_compile(
    pattern=r'^(?P<status_code>[0-9]{3})(\s(?P<enhanced_status_code>[0-9]\.[0-9]\.[0-9]))?\s(?P<text>.+)$'
)

_SMTP_MULTILINE_RESPONSE_PATTERN: Final[RePattern] = re_compile(
    pattern=r'^(?P<status_code>[0-9]{3})(-(?P<enhanced_status_code>[0-9]\.[0-9]{1,3}\.[0-9]{1,3}))?-(?P<text>.+)$'
)

_SMTP_COMMAND_PATTERN: Final[RePattern] = re_compile(
    pattern=r'^(?P<command>[^ ]+)( (?P<arguments>.+))?$'
)

_SMTP_QUEUED_AS_PATTERN: Final[RePattern] = re_compile(
    pattern=r'^250( 2\.0\.0)? Ok: ([0-9]+ bytes )?queued as (?P<queue_id>.+)$'
)

_ENHANCED_STATUS_CODE_PATTERN: Final[RePattern] = re_compile(
    pattern='^(?P<class>[0-9]{1,3})\.(?P<subject>[0-9]{1,3})\.(?P<detail>[0-9]{1,3})$'
)


@dataclass
class ExtraExchangeData:
    queue_id: str | None = None
    error_message: str | None = None
    error_code: str | None = None
    error_type: str | None = None


def parse_transcript(transcript_data: str) -> tuple[list[SMTPExchange], ExtraExchangeData | None]:

    extra_exchange_data = ExtraExchangeData()

    transcript_data_lines = transcript_data.splitlines()
    if not transcript_data_lines:
        return [], extra_exchange_data

    smtp_exchange_list: list[SMTPExchange] = []
    smtp_request: SMTPRequest | None = None
    response_lines: list[str] = []

    for line in transcript_data_lines:
        if match := _SMTP_RESPONSE_PATTERN.match(string=line):
            group_dict: dict[str, str] = match.groupdict()

            response_lines.append(group_dict['text'])

            enhanced_status_code_ecs: SMTPEnhancedStatusCode | None = None

            if enhanced_status_code := group_dict.get('enhanced_status_code'):
                enhanced_status_code_ecs = SMTPEnhancedStatusCode(original=enhanced_status_code)
                if enhanced_status_code_match := _ENHANCED_STATUS_CODE_PATTERN.match(string=enhanced_status_code):
                    enhanced_status_code_group_dict: dict[str, str] = enhanced_status_code_match.groupdict()

                    class_: str = enhanced_status_code_group_dict['class']
                    enhanced_status_code_ecs.class_ = class_
                    enhanced_status_code_ecs.class_text = CLASS_TO_TEXT.get(class_)

                    subject: str = enhanced_status_code_group_dict['subject']
                    enhanced_status_code_ecs.subject = subject
                    enhanced_status_code_ecs.subject_text = SUBJECT_TO_TEXT.get(subject)

                    detail: str = enhanced_status_code_group_dict['detail']
                    enhanced_status_code_ecs.detail = detail
                    enhanced_status_code_ecs.detail_text = SUBJECT_DETAIL_TO_TEXT.get((subject, detail))

            smtp_exchange_list.append(
                SMTPExchange(
                    request=smtp_request,
                    response=SMTPResponse(
                        status_code=group_dict['status_code'],
                        enhanced_status_code=enhanced_status_code_ecs,
                        lines=response_lines
                    )
                )
            )

            smtp_request = None
            response_lines = []

            if match := _SMTP_QUEUED_AS_PATTERN.match(string=line):
                extra_exchange_data.queue_id = match.groupdict()['queue_id']

        elif match := _SMTP_MULTILINE_RESPONSE_PATTERN.match(string=line):
            response_lines.append(match.groupdict()['text'])
        elif match := _SMTP_COMMAND_PATTERN.match(string=line):
            group_dict = match.groupdict()
            smtp_request = SMTPRequest(
                command=group_dict['command'].upper(),
                arguments_string=group_dict['arguments']
            )
        else:
            # TODO: Fix exception.
            raise ValueError(f'Malformed SMTP line?: {line}')

    if not extra_exchange_data.queue_id:
        for smtp_exchange in reversed(smtp_exchange_list):
            if response := smtp_exchange.response:
                response_text: str | None = ' '.join(response.lines) if response.lines else None

                if enhanced_status_code_ecs := response.enhanced_status_code:
                    if (class_ := enhanced_status_code_ecs.class_) and class_ in {'4', '5'}:
                        extra_exchange_data.error_code = enhanced_status_code_ecs.original
                        extra_exchange_data.error_message = response_text or enhanced_status_code_ecs.detail_text
                        extra_exchange_data.error_type = 'No message was queued.'
                        break

                if (status_code := response.status_code) and status_code[0] in {'4', '5'}:
                    extra_exchange_data.error_code = status_code
                    extra_exchange_data.error_message = response_text
                    extra_exchange_data.error_type = 'No message was queued.'
                    break

    return smtp_exchange_list, extra_exchange_data
