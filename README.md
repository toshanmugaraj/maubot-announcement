# Announcement Bot

## Overview

The Announcement Bot is a plugin designed for use with the Mautrix framework. It allows users to send announcement messages from one room to multiple other users as 1 to 1 private chat room. This bot is used to send anonymous messages to users similar to server notices but with more custom option.

# Announcement Bot Functionality

1. **Private Room Creation**:
   - An admin can create a private room specifically for sending announcements using the announcement bot.

2. **Sending Announcements**:
   - The admin can send announcements through this private room.
   - The bot will deliver these announcements to users configured as "allowed users" in the bot's configuration file. Each user will receive the messages in their own direct private room.

3. **Updating Room Details**:
   - The admin has the ability to update the private room’s topic, name, and avatar.
   - Any changes made by the admin will automatically be updated in all users' private rooms that are associated with the bot.

4. **Multiple Rooms**:
   - The admin can create multiple private rooms, each with different topics.
   - The bot will handle the creation of separate rooms for each topic, ensuring that messages are delivered according to the specific topic of each room.
     
## Features

- Announce messages from a specified room to multiple allowed users in private rooms.
- Handles state events (name, topic, avatar) and syncs them across rooms.
- Configurable through an easy-to-use configuration file.

## To-Do List

- Manage edited messages by tracking original message IDs and updating forwarded messages accordingly.
- Implement support for encrypted rooms for announcements.
- Add options to edit and delete messages in announcements.
- Introduce element widget-based configuration for easier setup and management.
- 
## Requirements

- Python 3.7 or higher
- Mautrix framework
- Necessary dependencies specified in the requirements.txt (if applicable)

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/toshanmugaraj/maubot-announcement.git
   cd announcement-bot

2. ** Configuration **:list of users who can engage Bot to broadcast message
   admins:
     - '@raj:xxxx.com'
3. Create any new room, and if the room admin user is in the above `admins` configuration , he can invite the bot.
4. Set the room state with list of the users that need to be broadcasted by the Bot.

   `{
     "type": "org.minbh.announcement",
     "sender": "@raj:albgninc.com",
     "content": {
       "Live": [
         "@user11:albgninc.com",
         "@user10:albgninc.com"
       ]
     }
     }
   `
