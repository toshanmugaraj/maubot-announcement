from maubot import MessageEvent, Plugin
from maubot.handlers import command, event
from mautrix.types import EventType, Membership, RoomAlias, StateEvent
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.types import RoomDirectoryVisibility, RoomCreatePreset, RoomID
from mautrix.api import Method, Path
from typing import List, Dict, Any, Type, Optional
from mautrix.types import PaginationDirection
import json
import asyncio
from collections import deque

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

    async def process_queue(self):
        normal_sleep_time = self.sleep_time 
        while True:
            try:
                # Check for high-priority messages first
                if self.high_priority_queue:
                    async with self.lock:
                        message = self.high_priority_queue.popleft()  # Get high-priority message
                elif self.message_queue:
                    async with self.lock:
                        message = self.message_queue.popleft()  # Get regular message
                else:
                    await asyncio.sleep(normal_sleep_time)  # Sleep briefly if both queues are empty
                    self.log.debug(f"Waiting..................")
                    continue  # Go back to the start of the loop

                # Send the message
                try:
                    if message.get('read_receipt'):
                        await self.client.send_message(message['room_id'], message['content'])
                    else: 
                        self.log.debug(f"Will send message ..................{message['room_id']}, {message['content']}")
                        event_id = await self.client.send_message(message['room_id'], message['content'])
                        if event_id:
                            message_content = {
                                "msgtype": "m.text",
                                "body": f"🔔 *Sent for*:{message['user']}",
                                "format": "org.matrix.custom.html",
                                "formatted_body": f"🔔 <em>Sent for</em>: {message['user']}",
                                "m.relates_to": {
                                    'rel_type': 'm.thread',
                                    'event_id': message['origin_evt_id']
                                }
                            }
                            message_read = {
                                "room_id": message['origin_room_id'],
                                "content": message_content,
                                "read_receipt": True
                            }

                            async with self.lock:
                                self.high_priority_queue.append(message_read)  # Always add high-priority messages
                    self.sleep_time = normal_sleep_time
                except Exception as e:
                    error_message = str(e)
                    if "Too Many Requests" in error_message:
                        self.sleep_time *= 2 
                        self.log.warning(f"Rate limit hit! Increasing sleep time {self.sleep_time}.")
                        await asyncio.sleep(self.sleep_time)
                        if message.get('read_receipt'):
                            self.high_priority_queue.appendleft(message)
                        else:
                            self.message_queue.appendleft(message)
                        continue
                    else:
                        self.log.error(f"Error sending message: {e}")
            except Exception as e:
                self.log.error(f"Error processing message: {e}")
                await asyncio.sleep(self.sleep_time)  # Optional: wait briefly before trying again


    async def start(self) -> None:
        """Start the plugin and load configuration."""
        await super().start()
        self.config.load_and_update()
              # Initialize the queues and other variables
        self.message_queue = deque()
        self.high_priority_queue = deque()
        self.lock = asyncio.Lock()
        self.rate_limit_per_second = 0.9 
        self.sleep_time = 1 / self.rate_limit_per_second

        # Start processing the queue as a background task
        asyncio.create_task(self.process_queue())

    @event.on(EventType.ROOM_REDACTION)
    async def handle_message_redact_event(self, evt: MessageEvent) -> None:
        """Handle incoming room messages."""
        admin_users = self.config["admins"]

        self.log.debug(f"Event received of type: {evt.type}")
        if evt.sender in admin_users:
            room_state = await self.fetch_room_state(evt.room_id)
            allowed_users = await self.extract_annoucment_members(room_state)
            allowed_users_str = ', '.join(allowed_users)
            self.log.debug(f"redacted event id {evt.redacts}")

            for user in allowed_users:
                existing_room_id = await self.get_existing_private_room(evt.room_id, user)
                if existing_room_id:
                    await self.get_and_redact_messages(existing_room_id, evt.redacts)

    @event.on(EventType.ROOM_MESSAGE)
    async def handle_message_event(self, evt: MessageEvent) -> None:
        """Handle incoming room messages."""
        admin_users = self.config["admins"]

        self.log.debug(f"Event received of type: {evt.type}")
        if evt.sender in admin_users:
            room_state = await self.fetch_room_state(evt.room_id)
            allowed_users = await self.extract_annoucment_members(room_state)
            allowed_users_str = ', '.join(allowed_users)
            self.log.debug(f"annoucement members {allowed_users_str}")
            evt.content["origin_event_id"] = evt.event_id
            await self.client.send_receipt(evt.room_id, evt.event_id, "m.read")
            await self.announce_message_to_allowed_users(evt, allowed_users, evt.room_id, room_state)

    async def announce_message_to_allowed_users(self, evt: MessageEvent, allowed_users, announcement_room_id, room_state):
        """Announce messages to allowed users in private rooms."""
        for user in allowed_users:
            private_room_id = await self.create_or_join_private_room(user, announcement_room_id, room_state)
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
            room_state = await self.fetch_room_state(evt.room_id)
            allowed_users = await self.extract_annoucment_members(room_state)
            self.log.debug(f"Event received of type: {evt.type}")
            self.log.debug(f"Allowed users count: {len(allowed_users)}")

            for user in allowed_users:
                existing_room_id = await self.get_existing_private_room(evt.room_id, user)
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

    # Room state fetching and extraction methods
    async def fetch_room_state(self, room_id: RoomID) -> List[Dict[str, Any]]:
        """Fetch the full state of the room."""
        response = await self.client.api.request(Method.GET, Path.v3.rooms[room_id].state)
        return response

    async def extract_room_topic(self, state_events) -> str:
        """Extract the room topic from the state events."""
        topic_event = next((e for e in state_events if e["type"] == "m.room.topic"), None)
        return topic_event["content"].get("topic", "") if topic_event else ""

    async def extract_annoucment_members(self, room_state) -> List:
        """Extract the room avatar from the state events."""
        avatar_event = next((e for e in room_state if e["type"] == "org.minbh.announcement"), None)
        return avatar_event["content"].get("Live", []) if avatar_event else ""
    
    async def extract_room_avatar(self, state_events) -> str:
        """Extract the room avatar from the state events."""
        avatar_event = next((e for e in state_events if e["type"] == "m.room.avatar"), None)
        return avatar_event["content"].get("url", "") if avatar_event else ""

    async def extract_room_name(self, state_events) -> str:
        """Extract the room name from the state events."""
        name_event = next((e for e in state_events if e["type"] == "m.room.name"), None)
        return name_event["content"].get("name", "") if name_event else ""

    def extract_room_matches_announcement(self, announcement_room_id, state_events) -> bool:
        """Check if the room matches the announcement criteria."""
        custom_event = next((e for e in state_events if e["type"] == "org.minbh.announcement"), None)
        if custom_event:
            self.log.debug(f"Room ID match {custom_event['content'].get('announcement_room_id', '')}.")
            return custom_event["content"].get("announcement_room_id", "") == announcement_room_id
        return False

    async def create_or_join_private_room(self, user_id: str, announcement_room: RoomID, room_states: List[Dict[str, Any]]) -> Optional[RoomID]:
        """Create or join a private room for a user."""
        existing_room_id = await self.get_existing_private_room(announcement_room, user_id)
        
        if existing_room_id:
            self.log.debug(f"Found existing room: {existing_room_id}. Joining the room.")
            return existing_room_id

        # Create a new private room if no existing room is found
        topic = await self.extract_room_topic(room_states)
        name = await self.extract_room_name(room_states)
        avatar_url = await self.extract_room_avatar(room_states)
        self.log.debug(f"No existing room found. Creating a new private room with avatar {avatar_url}.")

        room_options = {
            "visibility": RoomDirectoryVisibility.PRIVATE,
            "invitees": [user_id],
            "preset": RoomCreatePreset.PRIVATE,
            "topic": topic,
            "name": "[ " + name + " ]",
            "is_direct": False,
            "initial_state": [
                {
                    "type": "org.minbh.announcement",
                    "state_key": "",
                    "content": {
                        "announcement_room_id": announcement_room,
                    }
                },
                {
                    "type": "m.room.avatar",
                    "state_key": "",
                    "content": {
                        "url": avatar_url
                    }
                },
                {
                    "type": "m.room.power_levels",
                    "state_key": "",
                    "content": {
                        "users": {
                            self.client.mxid: 100,
                            user_id: 0,
                        },
                        "users_default": 0,
                        "events": {
                            "m.room.message": 100,
                            "m.room.member": 100,
                            "m.room.power_levels": 100,
                        },
                        "events_default": 0,
                    }
                }
            ]
        }

        # Attempt to create the room
        try:
            response = await self.client.create_room(**room_options)
            self.log.debug(f"Room created: {response}")
            return response
        except Exception as e:
            self.log.error(f"Failed to create room: {e}")
            return None

    async def get_existing_private_room(self, announcement_room: RoomID, other_user_id: str) -> Optional[RoomID]:
        """Check for existing private rooms with the specified user."""
        bots_joined_rooms = await self.client.get_joined_rooms()
        
        for room_id in bots_joined_rooms:
            try:
                member_events = await self.client.get_members(room_id)
                self.log.debug(f"Member events count: {len(member_events)}")

                if len(member_events) == 2 and other_user_id in [evt.state_key for evt in member_events]:
                    room_state = await self.fetch_room_state(room_id)

                    if self.extract_room_matches_announcement(announcement_room, room_state):
                        membership = next(
                            (evt.content.get('membership') for evt in member_events if evt.state_key == other_user_id),
                            None
                        )
                        self.log.debug(f"Membership type for {other_user_id}: {membership}")

                        if membership in [Membership.JOIN, Membership.INVITE]:
                            self.log.debug(f"Returning room ID: {room_id}")
                            return room_id
                        else:
                            await self.client.leave_room(room_id, "")
                            self.log.debug(f"Left empty room {room_id}.")

                self.log.debug("No matching room found")
            except Exception as e:
                self.log.error(f"Failed to get members: {e}")
                continue
        return None

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config