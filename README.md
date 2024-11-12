# Announcement Bot

## Overview

The Announcement Bot is a plugin designed for use with the Mautrix framework. It allows users to send announcement messages from one room to multiple other users as 1 to 1 private chat room. This bot is used to send anonymous messages to users similar to server notices but with more custom option.

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
   git clone https://github.com/yourusername/announcement-bot.git
   cd announcement-bot
