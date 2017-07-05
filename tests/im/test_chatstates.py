########################################################################
# File name: test_chatstates.py
# This file is part of: aioxmpp
#
# LICENSE
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.
#
########################################################################
import unittest
import unittest.mock

from aioxmpp.chatstates import ChatState

from aioxmpp.im.conversation import AbstractConversation
from aioxmpp.im.chatstates import ChatStatesMixin

from aioxmpp.stanza import Message
from aioxmpp.structs import MessageType

from aioxmpp.im.conversation import (
    ConversationFeature,
    ConversationState
)


class DummyConversation(AbstractConversation):
    def __init__(self, *args, **kwargs):
        self.__mock = kwargs["mock"]
        del kwargs["mock"]
        super().__init__(*args, **kwargs)

    @property
    def members(self):
        return [
            unittest.mock.sentinel.me,
            unittest.mock.sentinel.other,
        ]

    @property
    def me(self):
        return unittest.mock.sentinel.me

    @property
    def jid(self):
        pass

    def send_message_tracked(self, *args, **kwargs):
        return self.__mock.send_message_tracked(*args, **kwargs)


class DummyChatStateConversation(ChatStatesMixin, DummyConversation,
                                 AbstractConversation):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class TestChatStateMixin(unittest.TestCase):
    def setUp(self):
        self.cc = unittest.mock.sentinel.client
        self.parent = unittest.mock.sentinel.parent
        self.svc = unittest.mock.Mock(["client", "_conversation_left"])
        self.svc.client = self.cc
        self.c_mock = unittest.mock.Mock()
        self.c = DummyChatStateConversation(self.svc,
                                            parent=self.parent,
                                            mock=self.c_mock)

        self.c_mock.send_message_tracked.return_value = (
            unittest.mock.sentinel.token,
            unittest.mock.Mock()
        )

    def tearDown(self):
        del self.c_mock
        del self.c
        del self.parent
        del self.cc

    def test_features(self):
        self.assertCountEqual(
            self.c.features,
            [ConversationFeature.SET_STATE]
        )

    def test_set_state(self):
        self.c.set_state(ConversationState.COMPOSING)

        # check for idempotence
        self.c.set_state(ConversationState.COMPOSING)

        self.assertEqual(len(self.c_mock.mock_calls), 1)
        (_, args, _), = self.c_mock.send_message_tracked.mock_calls
        self.assertEqual(args[0].body, {})
        self.assertEqual(args[0].xep0085_chatstate, ChatState.COMPOSING)

    def test_DiscoverFeature_disables_sending_on_no_reply(self):
        # simulate an incoming message
        msg = Message(MessageType.NORMAL)
        msg.body[None] = "Message"
        self.c._on_message(
            msg,
            unittest.mock.sentinel.other,
            unittest.mock.Mock()
        )

        msg = Message(MessageType.NORMAL)
        self.c.send_message(msg)

        self.assertEqual(len(self.c_mock.mock_calls), 1)
        (_, args, _), = self.c_mock.mock_calls
        self.assertIsNone(args[0].xep0085_chatstate)

    def test_inject_chatstate(self):
        msg = Message(MessageType.NORMAL)
        msg.body[None] = "Message"
        token = self.c.send_message(msg)
        self.assertIs(token, unittest.mock.sentinel.token)
        self.assertEqual(len(self.c_mock.mock_calls), 1)
        (_, args, _), = self.c_mock.mock_calls
        self.assertEqual(args[0].xep0085_chatstate, ChatState.ACTIVE)

    def test_filter_empty_message(self):
        msg = Message(MessageType.NORMAL)
        msg.xep0085_chatstate = ChatState.COMPOSING
        self.c._on_message(
            msg,
            unittest.mock.sentinel.other,
            unittest.mock.Mock()
        )
        self.assertEqual(len(self.c_mock.mock_calls), 0)
