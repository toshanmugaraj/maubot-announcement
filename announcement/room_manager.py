from mautrix.types import RoomID, Membership
from mautrix.api import Method, Path
from typing import Optional, List, Dict, Any
from typing import TYPE_CHECKING
from mautrix.types import RoomDirectoryVisibility, RoomCreatePreset, RoomID

if TYPE_CHECKING:
    from announcement.bot import Announcement
class RoomManager:
    def __init__(self, announcement: 'Announcement'):
        self.announcement = announcement
        self.client = announcement.client
        self.log = announcement.log

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

        custom_event = next((e for e in room_states if e.get("type") == 'm.room.encryption'), None)
        is_room_encrypted = custom_event is not None

        room_options = {
            "visibility": RoomDirectoryVisibility.PRIVATE,
            "invitees": [user_id],
            "preset": RoomCreatePreset.PRIVATE,
            "topic": topic,
            "name": name + " 🦄",
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

        if is_room_encrypted:
            room_options["initial_state"].append({
                "type": "m.room.encryption",
                "sender": self.client.mxid,
                "content": {
                    "algorithm": "m.megolm.v1.aes-sha2"
                },
            })
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
        minbh = next((e for e in room_state if e["type"] == "org.minbh.announcement"), None)
        self.log.debug(f"extract members {minbh["content"].get("Live", []) if minbh else ""}.")
        return minbh["content"].get("Live", []) if minbh else ""
    
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