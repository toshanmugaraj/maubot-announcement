from maubot import MessageEvent, Plugin
from maubot.handlers import command, event
from mautrix.types import EventType, Membership, RoomAlias, StateEvent
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.types import RoomDirectoryVisibility, RoomCreatePreset, RoomID
from mautrix.api import Method, Path
from typing import List, Dict, Any, Type, Optional
from mautrix.types import PaginationDirection
import asyncio
from collections import deque
from announcement.queu_processor import QueueProcessor
from announcement.room_manager import RoomManager

# Define state event types
NAME_STATE_EVENT = EventType.find("m.room.name", EventType.Class.STATE)
TOPIC_STATE_EVENT = EventType.find("m.room.topic", EventType.Class.STATE)
AVATAR_STATE_EVENT = EventType.find("m.room.avatar", EventType.Class.STATE)
REDACT_TIMELINE_EVENT = EventType.find("org.minbh.announcement", EventType.Class.MESSAGE)

# Configuration class for the bot
class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("admins")

# Main bot plugin class
class Announcement(Plugin):

    async def start(self) -> None:
        """Start the plugin and load configuration."""
        await super().start()
        self.config.load_and_update()
        self.message_queue = deque()
        self.high_priority_queue = deque()
        self.lock = asyncio.Lock()
        self.rate_limit_per_second = 0.9 
        self.sleep_time = 1 / self.rate_limit_per_second
        self.queue_processor = QueueProcessor(self)
        self.room_manager = RoomManager(self)
        asyncio.create_task(self.queue_processor.process_queue())

    @event.on(EventType.ROOM_REDACTION)
    async def handle_message_redact_event(self, evt: MessageEvent) -> None:
        """Handle incoming room messages."""
        admin_users = self.config["admins"]

        self.log.debug(f"Event received of type: {evt.type}")
        if evt.sender in admin_users:
            room_state = await self.room_manager.fetch_room_state(evt.room_id)
            allowed_users = await self.room_manager.extract_annoucment_members(room_state)
            allowed_users_str = ', '.join(allowed_users)
            self.log.debug(f"redacted event id {evt.redacts}")

            for user in allowed_users:
                existing_room_id = await self.room_manager.get_existing_private_room(evt.room_id, user)
                if existing_room_id:
                    await self.get_and_redact_messages(existing_room_id, evt.redacts)

    @event.on(EventType.ROOM_MESSAGE)
    async def handle_message_event(self, evt: MessageEvent) -> None:
        """Handle incoming room messages."""
        admin_users = self.config["admins"]

        self.log.debug(f"Event received of type: {evt.type}")
        if evt.sender in admin_users:
            room_state = await self.room_manager.fetch_room_state(evt.room_id)
            allowed_users = await self.room_manager.extract_annoucment_members(room_state)
            allowed_users_str = ', '.join(allowed_users)
            self.log.debug(f"annoucement members {allowed_users_str}")
            evt.content["origin_event_id"] = evt.event_id
            await self.client.send_receipt(evt.room_id, evt.event_id, "m.read")
            await self.announce_message_to_allowed_users(evt, allowed_users, evt.room_id, room_state)

    async def announce_message_to_allowed_users(self, evt: MessageEvent, allowed_users, announcement_room_id, room_state):
        """Announce messages to allowed users in private rooms."""
        for user in allowed_users:
            private_room_id = await self.room_manager.create_or_join_private_room(user, announcement_room_id, room_state)
            if private_room_id:
                message = {
                    "origin_room_id": evt.room_id,
                    "origin_evt_id": evt.event_id,
                    "room_id": private_room_id,
                    "content": evt.content,
                    "user": user
                }
                self.log.debug(f"Will announce to allowed user {user}")
                async with self.lock:
                     self.message_queue.append(message) 


    async def handle_state_event(self, evt: StateEvent) -> None:
        """Handle state events (name, topic, avatar)."""
        admin_users = self.config["admins"]

        if evt.sender in admin_users:
            room_state = await self.room_manager.fetch_room_state(evt.room_id)
            allowed_users = await self.extract_annoucment_members(room_state)
            self.log.debug(f"Event received of type: {evt.type}")
            self.log.debug(f"Allowed users count: {len(allowed_users)}")

            for user in allowed_users:
                existing_room_id = await self.room_manager.get_existing_private_room(evt.room_id, user)
                if existing_room_id:
                    await self.client.send_state_event(existing_room_id, evt.type, evt.content)

    async def get_and_redact_messages(self, room_id: str,  redact_event_id: str, limit: int = 5): 

        # Define the filter to include only messages with the specified origin_event_id
        filter_param = {
            "room": {
                "timeline": {
                    "limit": limit,
                    "filter": {
                        "types": ["m.room.message"],
                        "contains": {
                            "origin_event_id": redact_event_id
                        }
                    }
                }
            }
        }
        self.log.debug(f"get messages for redact id {redact_event_id}")

        start, end, events  = await self.client.get_messages(
            room_id=room_id,
            direction=PaginationDirection.BACKWARD,
            limit=limit,
            filter_json=filter_param
        )
        self.log.debug(f"received messages for redaction {events}")

        # Iterate over the messages and filter based on origin_server_ts
        for event in events:
            try:
                origin_event_id = getattr(event.content, 'origin_event_id', None)
                self.log.debug(f"origin_event_id : {origin_event_id} vs {redact_event_id}")

                if origin_event_id is not None:
                    if origin_event_id == redact_event_id:
                        redacted = await self.client.redact(room_id=room_id, event_id=event.event_id) 
                        self.log.debug(f"Redacted event: {redacted}")
            except Exception as e:
                self.log.debug(f"Error redacting event {event.event_id}: {e}")

    # Usage
    # Ensure that you have a valid client instance and room_id, start_time, and end_time
    # await get_and_redact_messages(client, room_id, start_time, end_time)

    # Event handlers for specific state events
    @event.on(NAME_STATE_EVENT)
    async def check_name_event(self, evt: StateEvent) -> None:
        await self.handle_state_event(evt)

    @event.on(TOPIC_STATE_EVENT)
    async def check_topic_event(self, evt: StateEvent) -> None:
        await self.handle_state_event(evt)

    @event.on(AVATAR_STATE_EVENT)
    async def check_avatar_event(self, evt: StateEvent) -> None:
        await self.handle_state_event(evt)

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config