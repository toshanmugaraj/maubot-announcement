from mautrix.types import RoomID, Membership
from mautrix.api import Method, Path
from typing import Optional, List, Dict, Any
from typing import TYPE_CHECKING
from mautrix.types import RoomDirectoryVisibility, RoomCreatePreset, RoomID, EventType
import uuid
from maubot import MessageEvent

ANNOUNCEMENT_STATE_EVENT = EventType.find("org.minbh.announcement", EventType.Class.STATE)


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
            self.log.warning(f"Found existing room: {existing_room_id}. Joining the room.")
            return existing_room_id

        # Create a new private room if no existing room is found
        topic =  self.extract_room_topic(room_states)
        name =  self.extract_room_name(room_states)
        avatar_url =  self.extract_room_avatar(room_states)

        custom_event = next((e for e in room_states if e.get("type") == 'm.room.encryption'), None)
        is_room_encrypted = custom_event is not None

        room_options = {
            "visibility": RoomDirectoryVisibility.PRIVATE,
            "invitees": [user_id],
            "preset": RoomCreatePreset.PRIVATE,
            "topic": topic,
            "name": name + " 📣",
            "is_direct": False,
            "initial_state": [
                {
                    "type": "org.minbh.announcement.receiver",
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
                        "events_default": 50,
                    }
                }
            ]
        }

        # if is_room_encrypted:
        #     room_options["initial_state"].append({
        #         "type": "m.room.encryption",
        #         "sender": self.client.mxid,
        #         "content": {
        #             "algorithm": "m.megolm.v1.aes-sha2"
        #         },
        #     })
        try:
            response = await self.client.create_room(**room_options)
            self.log.warning(f"Room created: {response}")
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

                    if self.extract_room_matches_announcement_receiver(announcement_room, room_state):
                        membership = next(
                            (evt.content.get('membership') for evt in member_events if evt.state_key == other_user_id),
                            None
                        )
                        self.log.warning(f"Membership type for {other_user_id}: {membership}")

                        if membership in [Membership.JOIN, Membership.INVITE]:
                            self.log.warning(f"Returning room ID: {room_id}")
                            return room_id
                        else:
                            await self.client.leave_room(room_id, "")
                            self.log.warning(f"Left empty room {room_id}.")

                self.log.debug("No matching room found")
            except Exception as e:
                self.log.error(f"Failed to get members: {e}")
                continue
        return None

    async def update_user_room_general_members(self, room_id: RoomID, admin_id: str, config: Dict[str, Any]) -> None:
        try:
            room_state = await self.fetch_room_state(room_id)
            
            # Check if this is an announcer---bot room
            if self.extract_room_matches_announcement_receiver(room_id, room_state):
                return

            if self.extract_bot_power(room_state) < 50:
                return
            
            user_groups = self.get_general_users_for_admin(config, admin_id)
            
            # Get existing Live members from room state
            existing_live_users =  self.extract_annoucment_members(room_state) or []

            filtered_live_users = []
            # Check if minbh is None in the room_state
            if not self.check_already_minbh_in_room_state(room_state):
                filtered_live_users = user_groups
            else:
                filtered_live_users = [user for user in existing_live_users if user in user_groups]
                        
            # Prepare updated state content
            updated_state = {
                "General": user_groups,  # Update General users
                "Live": filtered_live_users  # Update filtered Live users
            }
            
            # Send the updated state event
            await self.client.send_state_event(
                room_id,
                "org.minbh.announcement",
                updated_state
            )
            widget_url = config.get("widget_url", "")
            self.log.warning(f"widget url  {widget_url} ")

            if widget_url and not self.is_widget_registered(room_state):  # Check if widget_url is not blank
                # Update widget state
                widget_state = {
                    "type": "com.minbh.announcement",
                    "url": widget_url,
                    "name": "Announcement Widget",
                    "data": {
                        "title": "Send announcement"
                    }
                }

                random_id = str(uuid.uuid4())

                await self.client.send_state_event(
                    room_id,
                    "im.vector.modular.widgets",
                    widget_state,
                    state_key=random_id
                )
            
            self.log.warning(f"Updated room state for {updated_state} ")
                
        except Exception as e:
            self.log.error(f"Failed to update room state for room {room_id}: {e}")

    async def update_room_general_members(self, config: Dict[str, Any]) -> None:

        bots_joined_rooms = await self.client.get_joined_rooms()
        
        for room_id in bots_joined_rooms:
            try:
                
                # Get all members in the room
                member_events = await self.client.get_members(room_id)
                member_ids = [evt.state_key for evt in member_events]

                

                # Skip if not a private room (more than 2 members)
                if len(member_ids) != 2:
                    self.log.debug(f"member_ids: {len(member_ids)}")                    
                    continue
                    
                # Find the other user in the room (excluding our bot)
                bot_previledged_user = next((uid for uid in member_ids if uid != self.client.mxid), None)
                self.log.debug(f"bot previledged: {bot_previledged_user}")
                if not bot_previledged_user:
                    continue

                if bot_previledged_user not in self.get_admin_users(config):
                    continue
                
                await self.update_user_room_general_members(room_id, bot_previledged_user, config)
                self.log.warning(f"Updated room state for {bot_previledged_user} in room {room_id}")
                
            except Exception as e:
                self.log.error(f"Failed to update room state for room {room_id}: {e}")
                continue

    async def fetch_room_state(self, room_id: RoomID) -> List[Dict[str, Any]]:
        """Fetch the full state of the room."""
        response = await self.client.api.request(Method.GET, Path.v3.rooms[room_id].state)
        return response

    def extract_room_topic(self, state_events) -> str:
        """Extract the room topic from the state events."""
        topic_event = next((e for e in state_events if e["type"] == "m.room.topic"), None)
        return topic_event["content"].get("topic", "") if topic_event else ""
    
    def is_widget_registered(self, room_state) -> bool:
        """Check if any widget in room_state is of type 'com.minbh.announcement'."""
        return any(
            e.get("type") == "im.vector.modular.widgets" and
            e.get("content", {}).get("type") == "com.minbh.announcement"
            for e in room_state
        )

    def extract_bot_power(self, room_state) -> int:
        """Extract the power level of sai3 from the state events."""
        power_levels = next((e for e in room_state if e["type"] == "m.room.power_levels"), None)
        if not power_levels:
            return -1  
        
        users = power_levels.get("content", {}).get("users", {})
        return users.get(self.client.mxid, 0) 
    
    def check_already_minbh_in_room_state(self, room_state) -> bool:
        """Check if minbh is None in the room_state."""
        minbh = next((e for e in room_state if e["type"] == "org.minbh.announcement"), None)
        return minbh is not None
    
    def extract_annoucment_members(self, room_state) -> List:
        """Extract the room avatar from the state events."""
        minbh = next((e for e in room_state if e["type"] == "org.minbh.announcement"), None)
        self.log.warning(f"extract members {minbh["content"].get("Live", []) if minbh else ""}.")
        return minbh["content"].get("Live", []) if minbh else ""

    def extract_room_avatar(self, state_events) -> str:
        """Extract the room avatar from the state events."""
        avatar_event = next((e for e in state_events if e["type"] == "m.room.avatar"), None)
        return avatar_event["content"].get("url", "") if avatar_event else ""

    def extract_room_name(self, state_events) -> str:
        """Extract the room name from the state events."""
        name_event = next((e for e in state_events if e["type"] == "m.room.name"), None)
        return name_event["content"].get("name", "") if name_event else ""

    def extract_room_matches_announcement_receiver(self, announcement_room_id, state_events) -> bool:
        """Check if the room matches the announcement criteria."""
        custom_event = next((e for e in state_events if e["type"] == "org.minbh.announcement.receiver"), None)
        if custom_event:
            self.log.warning(f"Room ID match {custom_event['content'].get('announcement_room_id', '')}.")
            return custom_event["content"].get("announcement_room_id", "") == announcement_room_id
        return False
    
    def extract_room_members(self, state_events) -> bool:
        """Check if the room matches the announcement criteria."""
        custom_event = next((e for e in state_events if e["type"] == "m.room.member"), None)
        if custom_event:
            self.log.warning(f"Extract room members {custom_event}.")
            self.log.warning(f"Extract room members {custom_event['content']}.")
            return  False
        return False
    
        
    def get_admin_users(self, config: Dict[str, Any]) -> List[str]:
        try:
            admin_config = config.get("admins", [])
            return [admin["user"] for admin in admin_config if "user" in admin]
        except Exception as e:
            self.log.error(f"Error getting admin users: {e}")
            return []
    
    def get_general_users_for_admin(self, config: Dict[str, Any], admin_id: str) -> List[str]:
        try:
            admin_config = config.get("admins", [])
            admin_data = next(
                (admin for admin in admin_config 
                if admin.get("user") == admin_id),
                None
            )
            
            if admin_data:
                return admin_data.get("general", [])
            return []
        
        except Exception as e:
            self.log.error(f"Error getting general users for admin {admin_id}: {e}")
            return []