import asyncio
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from announcement.bot import Announcement


class QueueProcessor:
    def __init__(self, announcement: 'Announcement'):
        self.announcement = announcement
        self.log = announcement.log

    async def process_queue(self):
        normal_sleep_time = self.announcement.sleep_time 
        while True:
            try:
                # Check for high-priority messages first
                if self.announcement.high_priority_queue:
                    async with self.announcement.lock:
                        message = self.announcement.high_priority_queue.popleft()  # Get high-priority message
                elif self.announcement.message_queue:
                    async with self.announcement.lock:
                        message = self.announcement.message_queue.popleft()  # Get regular message
                else:
                    await asyncio.sleep(normal_sleep_time)  # Sleep briefly if both queues are empty
                    self.log.debug(f"Waiting..................")
                    continue  # Go back to the start of the loop

                # Send the message
                try:
                    if message.get('read_receipt'):
                        await self.announcement.client.send_message(message['room_id'], message['content'])
                    else: 
                        self.log.debug(f"Will send message ..................{message['room_id']}, {message['content']}")
                        event_id = await self.announcement.client.send_message(message['room_id'], message['content'])
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

                            async with self.announcement.lock:
                                self.announcement.high_priority_queue.append(message_read)  # Always add high-priority messages
                    self.announcement.sleep_time = normal_sleep_time
                except Exception as e:
                    error_message = str(e)
                    if "Too Many Requests" in error_message:
                        self.announcement.sleep_time *= 2 
                        self.log.warning(f"Rate limit hit! Increasing sleep time {self.announcement.sleep_time}.")
                        if message.get('read_receipt'):
                            self.announcement.high_priority_queue.appendleft(message)
                        else:
                            self.announcement.message_queue.appendleft(message)
                        continue
                    else:
                        self.log.error(f"Error sending message: {e}")
            except Exception as e:
                self.log.error(f"Error processing message: {e}")
                await asyncio.sleep(self.announcement.sleep_time)  # Optional: wait briefly before trying again