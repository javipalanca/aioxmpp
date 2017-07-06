########################################################################
# File name: chatstates.py
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

import aioxmpp
import aioxmpp.im.conversation as conversation
import aioxmpp.chatstates as chatstates


INBOUND_STATE_MAP = {
    chatstates.ChatState.ACTIVE: conversation.ConversationState.ACTIVE,
    chatstates.ChatState.COMPOSING: conversation.ConversationState.COMPOSING,
    chatstates.ChatState.PAUSED: conversation.ConversationState.PAUSED,
    chatstates.ChatState.INACTIVE: conversation.ConversationState.INACTIVE,
    chatstates.ChatState.GONE: conversation.ConversationState.GONE,
}


OUTBOUND_STATE_MAP = {value: key for key, value in INBOUND_STATE_MAP.items()}


class ChatStatesMixin(conversation.AbstractConversation):
    """
    A mixin for :class:`~.im.conversation.AbstractConversation` which
    implements :xep:`Chat State Notifications <85>`.

    .. sealso::

        :class:`.im.conversation.AbstractConversation`
          for documentation on the interface implemented by this class.
    """

    def __init__(self, client, **kwargs):
        self.__state_manager = chatstates.ChatStateManager()
        self.__chatstate_cache = {}
        super().__init__(client, **kwargs)

    @aioxmpp.service.depsignal(conversation.AbstractConversation,
                               "on_leave")
    def __on_leave(self, member, **kwargs):
        self.__chatstate_cache.pop(member, None)

    @property
    def features(self):
        return (frozenset([conversation.ConversationFeature.SET_STATE]) |
                super().features)

    def _on_message(self, msg, member, source, tracker=None, **kwargs):
        if msg.xep0085_chatstate is not None:
            incoming_state = INBOUND_STATE_MAP[msg.xep0085_chatstate]
            if incoming_state != self.__chatstate_cache.get(member, None):
                self.__chatstate_cache[member] = incoming_state
                self.on_state_changed(
                    member,
                    incoming_state
                )

            if not msg.body:
                # filter empty chat-state notifications, the XEP
                # prescribes that nothing but thread and activity
                # information is allowed in a standalone activity
                # message without body
                return
        else:
            if msg.body and member is not self.me:
                self.__state_manager.no_reply()

        super()._on_message(msg, member, source, tracker=tracker, **kwargs)

    def send_message_tracked(self, msg, *, timeout=None):
        if self.__state_manager.sending and msg.xep0085_chatstate is None:
            msg.xep0085_chatstate = chatstates.ChatState.ACTIVE
        return super().send_message_tracked(msg, timeout=timeout)

    def set_state(self, state):
        state = OUTBOUND_STATE_MAP.get(state, chatstates.ChatState.ACTIVE)
        if self.__state_manager.handle(state):
            msg = aioxmpp.Message(aioxmpp.MessageType.NORMAL)
            msg.xep0085_chatstate = state
            super().send_message(msg)
