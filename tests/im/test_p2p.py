########################################################################
# File name: test_p2p.py
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
import asyncio
import contextlib
import unittest

import aioxmpp
import aioxmpp.service
import aioxmpp.muc.xso as muc_xso

import aioxmpp.im.p2p as p2p
import aioxmpp.im.service as im_service
import aioxmpp.im.dispatcher as im_dispatcher

from aioxmpp.im.conversation import ConversationFeature

from aioxmpp.testutils import (
    make_connected_client,
    CoroutineMock,
    run_coroutine,
)

from aioxmpp.e2etest import (
    blocking_timed,
    TestCase,
)


LOCAL_JID = aioxmpp.JID.fromstr("juliet@capulet.example/balcony")
PEER_JID = aioxmpp.JID.fromstr("romeo@montague.example")


class TestConversation(unittest.TestCase):
    def setUp(self):
        self.listener = unittest.mock.Mock()

        self.cc = make_connected_client()
        self.cc.stream.send = CoroutineMock()
        self.cc.local_jid = LOCAL_JID
        self.svc = unittest.mock.Mock(["client", "_conversation_left"])
        self.svc.client = self.cc

        self.c = p2p.Conversation(self.svc, PEER_JID)

        for ev in ["on_message"]:
            listener = getattr(self.listener, ev)
            signal = getattr(self.c, ev)
            listener.return_value = None
            signal.connect(listener)

    def tearDown(self):
        del self.cc

    def test_features(self):
        self.assertCountEqual(
            self.c.features,
            [ConversationFeature.SET_STATE,
             ConversationFeature.SEND_MESSAGE,
             ConversationFeature.SEND_MESSAGE_TRACKED,
             ConversationFeature.LEAVE]
        )

    def test_members_contain_both_entities(self):
        members = list(self.c.members)
        self.assertCountEqual(
            [PEER_JID, LOCAL_JID],
            [member.conversation_jid for member in members]
        )

        self.assertCountEqual(
            [True, False],
            [member.is_self for member in members]
        )

        self.assertSequenceEqual(
            [member.direct_jid for member in members],
            [member.conversation_jid for member in members]
        )

    def test_me(self):
        self.assertIn(self.c.me, self.c.members)
        self.assertEqual(
            self.c.me.direct_jid,
            LOCAL_JID,
        )
        self.assertTrue(
            self.c.me.is_self
        )

    def test_send_message_stamps_to_and_enqueues(self):
        msg = unittest.mock.Mock()
        token = self.c.send_message(msg)

        self.cc.stream.enqueue.assert_called_once_with(msg)
        self.assertEqual(msg.to, PEER_JID)

        self.listener.on_message.assert_called_once_with(
            msg,
            self.c.me,
            im_dispatcher.MessageSource.STREAM,
        )

        self.assertEqual(token, self.cc.stream.enqueue())

    def test_inbound_message_dispatched_to_event(self):
        msg = unittest.mock.sentinel.message
        msg.xep0085_chatstate = None
        msg.body = unittest.mock.Mock()
        self.c._handle_message(
            msg,
            unittest.mock.sentinel.from_,
            False,
            im_dispatcher.MessageSource.STREAM
        )
        self.listener.on_message.assert_called_once_with(
            msg,
            self.c.members[1],
            im_dispatcher.MessageSource.STREAM,
            tracker=None
        )

    def test_leave_calls_conversation_left(self):
        run_coroutine(self.c.leave())
        self.svc._conversation_left.assert_called_once_with(self.c)

    def test_jid(self):
        self.assertEqual(
            self.c.jid,
            PEER_JID,
        )

    def test_jid_not_writable(self):
        with self.assertRaises(AttributeError):
            self.c.jid = self.c.jid

    def test_message_tracking_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            run_coroutine(self.c.send_message_tracked(
                unittest.mock.sentinel.foo
            ))


class TestService(unittest.TestCase):
    def setUp(self):
        self.cc = make_connected_client()
        self.cc.stream.send = CoroutineMock()
        self.cc.stream.send.side_effect = AssertionError("not configured")
        self.cc.local_jid = LOCAL_JID
        deps = {
            im_service.ConversationService: im_service.ConversationService(
                self.cc
            ),
            im_dispatcher.IMDispatcher: im_dispatcher.IMDispatcher(
                self.cc
            )
        }
        self.svc = unittest.mock.Mock(["client", "_conversation_left"])
        self.svc.client = self.cc
        self.s = p2p.Service(self.cc, dependencies=deps)

        self.listener = unittest.mock.Mock()

        for ev in ["on_conversation_new", "on_conversation_left"]:
            listener = getattr(self.listener, ev)
            signal = getattr(self.s, ev)
            listener.return_value = None
            signal.connect(listener)

        for ev in ["on_conversation_added"]:
            listener = getattr(self.listener, ev)
            signal = getattr(deps[im_service.ConversationService], ev)
            listener.return_value = None
            signal.connect(listener)

    def tearDown(self):
        del self.cc

    def test_depends_on_conversation_service(self):
        self.assertLess(
            im_service.ConversationService,
            p2p.Service,
        )

    def test_depends_on_dispatcher_service(self):
        self.assertLess(
            im_dispatcher.IMDispatcher,
            p2p.Service,
        )

    def test_get_conversation_creates_conversation(self):
        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation"
            ))

            c = run_coroutine(self.s.get_conversation(PEER_JID))

        self.cc.stream.register_message_callback.assert_not_called()

        Conversation.assert_called_once_with(
            self.s,
            PEER_JID,
            parent=None,
        )

        self.assertEqual(
            c,
            Conversation(),
        )

    def test_get_conversation_emits_event(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation"
            ))

            c = run_coroutine(self.s.get_conversation(PEER_JID))

        self.listener.on_conversation_added.assert_called_once_with(c)

    def test_get_conversation_deduplicates(self):
        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation"
            ))

            c1 = run_coroutine(self.s.get_conversation(PEER_JID))
            c2 = run_coroutine(self.s.get_conversation(PEER_JID))

        Conversation.assert_called_once_with(
            self.s,
            PEER_JID,
            parent=None,
        )

        self.assertIs(c1, c2)

    def test_get_conversation_returns_fresh_after_leave(self):
        def generate_mocks():
            while True:
                yield unittest.mock.Mock()

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))
            Conversation.side_effect = generate_mocks()

            c1 = run_coroutine(self.s.get_conversation(PEER_JID))
            c1.peer_jid = PEER_JID
            self.s._conversation_left(c1)
            c2 = run_coroutine(self.s.get_conversation(PEER_JID))

        self.assertIsNot(c1, c2)

    def test_get_conversation_emits_on_conversation_new_and_left(self):
        def generate_mocks():
            while True:
                yield unittest.mock.Mock()

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))
            Conversation.side_effect = generate_mocks()

            c1 = run_coroutine(self.s.get_conversation(PEER_JID))
            self.listener.on_conversation_new.assert_called_once_with(c1)
            c1.peer_jid = PEER_JID
            self.s._conversation_left(c1)
            self.listener.on_conversation_left.assert_called_once_with(c1)
            c2 = run_coroutine(self.s.get_conversation(PEER_JID))
            self.listener.on_conversation_new.assert_called_with(c2)

        self.assertIsNot(c1, c2)

    def test_has_im_message_filter(self):
        self.assertTrue(
            aioxmpp.service.is_depfilter_handler(
                im_dispatcher.IMDispatcher,
                "message_filter",
                p2p.Service._filter_message,
            )
        )

    def test_message_filter_passes_stanzas(self):
        stanza = unittest.mock.Mock(["type_", "to", "from_", "id_"])
        self.assertIs(
            self.s._filter_message(
                stanza,
                stanza.from_,
                False,
                im_dispatcher.MessageSource.STREAM,
            ),
            stanza,
        )

    def test_autocreate_conversation_from_recvd_chat_with_body(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.CHAT,
            from_=PEER_JID.replace(resource="foo"),
        )
        msg.body[None] = "foo"

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIsNone(self.s._filter_message(
                msg,
                msg.from_,
                False,
                im_dispatcher.MessageSource.STREAM,
            ))
            Conversation.assert_called_once_with(
                self.s,
                msg.from_.bare(),
                parent=None
            )

            c = run_coroutine(self.s.get_conversation(PEER_JID))
            Conversation.assert_called_once_with(
                self.s,
                msg.from_.bare(),
                parent=None
            )

            self.assertEqual(c, Conversation())

            self.listener.on_conversation_new.assert_called_once_with(
                Conversation()
            )

            Conversation()._handle_message.assert_called_once_with(
                msg,
                msg.from_,
                False,
                im_dispatcher.MessageSource.STREAM,
            )

    def test_autocreate_based_on_peer(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.CHAT,
            from_=PEER_JID.replace(resource="foo"),
        )
        msg.body[None] = "foo"

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIsNone(self.s._filter_message(
                msg,
                PEER_JID.replace(localpart="fnord", resource="foo"),
                False,
                im_dispatcher.MessageSource.STREAM,
            ))
            Conversation.assert_called_once_with(
                self.s,
                PEER_JID.replace(localpart="fnord"),
                parent=None
            )

            c = run_coroutine(self.s.get_conversation(
                PEER_JID.replace(localpart="fnord")
            ))
            Conversation.assert_called_once_with(
                self.s,
                PEER_JID.replace(localpart="fnord"),
                parent=None
            )

            self.assertEqual(c, Conversation())

            self.listener.on_conversation_new.assert_called_once_with(
                Conversation()
            )

            Conversation()._handle_message.assert_called_once_with(
                msg,
                PEER_JID.replace(localpart="fnord", resource="foo"),
                False,
                im_dispatcher.MessageSource.STREAM,
            )

    def test_autocreate_with_fulljid_if_muc_tagged(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.CHAT,
            from_=PEER_JID.replace(resource="foo"),
        )
        msg.body[None] = "foo"
        msg.xep0045_muc_user = muc_xso.UserExt()

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIsNone(self.s._filter_message(
                msg,
                PEER_JID.replace(localpart="fnord", resource="foo"),
                False,
                im_dispatcher.MessageSource.STREAM,
            ))
            Conversation.assert_called_once_with(
                self.s,
                PEER_JID.replace(localpart="fnord", resource="foo"),
                parent=None
            )

            c = run_coroutine(self.s.get_conversation(
                PEER_JID.replace(localpart="fnord", resource="foo")
            ))
            Conversation.assert_called_once_with(
                self.s,
                PEER_JID.replace(localpart="fnord", resource="foo"),
                parent=None
            )

            self.assertEqual(c, Conversation())

            self.listener.on_conversation_new.assert_called_once_with(
                Conversation()
            )

            Conversation()._handle_message.assert_called_once_with(
                msg,
                PEER_JID.replace(localpart="fnord", resource="foo"),
                False,
                im_dispatcher.MessageSource.STREAM,
            )

    def test_autocreate_conversation_from_recvd_normal_with_body(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.NORMAL,
            from_=PEER_JID.replace(resource="foo"),
        )
        msg.body[None] = "foo"

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIsNone(self.s._filter_message(
                msg,
                msg.from_,
                False,
                im_dispatcher.MessageSource.STREAM,
            ))
            Conversation.assert_called_once_with(
                self.s,
                msg.from_.bare(),
                parent=None
            )

            c = run_coroutine(self.s.get_conversation(PEER_JID))
            Conversation.assert_called_once_with(
                self.s,
                msg.from_.bare(),
                parent=None
            )

            self.assertEqual(c, Conversation())

            self.listener.on_conversation_new.assert_called_once_with(
                Conversation()
            )

            Conversation()._handle_message.assert_called_once_with(
                msg,
                msg.from_,
                False,
                im_dispatcher.MessageSource.STREAM,
            )

    def test_no_autocreate_conversation_from_recvd_groupchat_with_body(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.GROUPCHAT,
            from_=PEER_JID.replace(resource="foo"),
        )
        msg.body[None] = "foo"

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIs(
                self.s._filter_message(
                    msg,
                    msg.from_,
                    False,
                    im_dispatcher.MessageSource.STREAM,
                ),
                msg
            )
            Conversation.assert_not_called()
            self.listener.on_conversation_new.assert_not_called()

    def test_no_autocreate_conversation_from_error_with_body(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.ERROR,
            from_=PEER_JID.replace(resource="foo"),
        )
        msg.body[None] = "foo"

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIs(
                self.s._filter_message(
                    msg,
                    msg.from_,
                    False,
                    im_dispatcher.MessageSource.STREAM,
                ),
                msg
            )
            Conversation.assert_not_called()
            self.listener.on_conversation_new.assert_not_called()

    def test_no_autocreate_conversation_from_other_with_body(self):
        msg = unittest.mock.Mock(["type_", "from_", "body"])

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIs(
                self.s._filter_message(
                    msg,
                    msg.from_,
                    False,
                    im_dispatcher.MessageSource.STREAM,
                ),
                msg
            )
            Conversation.assert_not_called()
            self.listener.on_conversation_new.assert_not_called()

    def test_no_autocreate_conversation_from_normal_without_body(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.NORMAL,
            from_=PEER_JID.replace(resource="foo"),
        )

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIs(
                self.s._filter_message(
                    msg,
                    msg.from_,
                    False,
                    im_dispatcher.MessageSource.STREAM,
                ),
                msg
            )
            Conversation.assert_not_called()
            self.listener.on_conversation_new.assert_not_called()

    def test_no_autocreate_conversation_from_chat_without_body(self):
        msg = aioxmpp.Message(
            type_=aioxmpp.MessageType.CHAT,
            from_=PEER_JID.replace(resource="foo"),
        )

        with contextlib.ExitStack() as stack:
            Conversation = stack.enter_context(unittest.mock.patch(
                "aioxmpp.im.p2p.Conversation",
            ))

            self.assertIs(
                self.s._filter_message(
                    msg,
                    msg.from_,
                    False,
                    im_dispatcher.MessageSource.STREAM,
                ),
                msg
            )
            Conversation.assert_not_called()
            self.listener.on_conversation_new.assert_not_called()


class TestE2E(TestCase):
    @blocking_timed
    @asyncio.coroutine
    def setUp(self):
        services = [p2p.Service]

        self.firstwitch, self.secondwitch, self.thirdwitch = \
            yield from asyncio.gather(
                self.provisioner.get_connected_client(
                    services=services
                ),
                self.provisioner.get_connected_client(
                    services=services
                ),
                self.provisioner.get_connected_client(
                    services=services
                ),
            )

    @blocking_timed
    @asyncio.coroutine
    def test_converse_with_preexisting(self):
        c1 = yield from self.firstwitch.summon(p2p.Service).get_conversation(
            self.secondwitch.local_jid.bare()
        )

        c2 = yield from self.secondwitch.summon(p2p.Service).get_conversation(
            self.firstwitch.local_jid.bare()
        )

        fwmsgs = []
        fwev = asyncio.Event()

        def fwevset(message, member, source, tracker=None):
            if member == c1.me:
                return
            fwmsgs.append(message)
            fwev.set()

        swmsgs = []
        swev = asyncio.Event()

        def swevset(message, member, source, tracker=None):
            if member == c2.me:
                return
            swmsgs.append(message)
            swev.set()

        c1.on_message.connect(fwevset)
        c2.on_message.connect(swevset)

        msg = aioxmpp.Message(aioxmpp.MessageType.CHAT)
        msg.body[None] = "foo"
        c1.send_message(msg)
        yield from swev.wait()

        self.assertEqual(len(swmsgs), 1)
        self.assertEqual(swmsgs[0].body[None], "foo")
        self.assertEqual(len(fwmsgs), 0)

        msg.body[None] = "bar"
        c2.send_message(msg)
        yield from fwev.wait()

        self.assertEqual(len(fwmsgs), 1)
        self.assertEqual(fwmsgs[0].body[None], "bar")
        self.assertEqual(len(swmsgs), 1)
