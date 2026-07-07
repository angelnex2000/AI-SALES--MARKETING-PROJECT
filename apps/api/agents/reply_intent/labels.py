from enum import Enum


class ReplyIntent(str, Enum):
    INTERESTED = "interested"
    FOLLOW_UP = "follow_up"
    REJECTED = "rejected"
    INFO_REQUEST = "info_request"
