# Karma Telegram Bot
Telegram bot built with Python. It was created to help track performance statistics for team members.

## Description
Bot connects to the group chats and monitors the keywords that will be used to award points to the members of the group.
This bot is built in Python and integrated with the Telegram Bot API.
---

## Features
- Track statistics for team members.
- Get data for a specific time period (month, quarter, year) for each member.
- Easily to view statistics.
- It is possible to generate statistics in Excel spreadsheet format.
- You can see the ranking of the top 10 participants.
- Easily to use.

---
## Installation
**1. Clone the repository:**
   ```shell
   git clone 
   ```
---
**2. Install the required dependencies using Poetry:**
  
* Check if Poetry is installed:
   ```shell
   poetry --version
   ```
   
* if installed, execute:
   ```shell
   cd karma-tg-bot/ poetry install
   ```
   
* if not installed, execute:
   ```shell
   curl -sSL https://install.python-poetry.org | python -
   ```
then add poetry to the PATH variable

---
**3. Create a `.env` file based on the `.env.example` file:**
   ```shell
   cd karma-tg-bot
   ```
   ```shell
   cp .env.example .env
   ```
---
**4. To run bot, execute:**
   ```shell
   poetry shell
   ```
   ```shell
   python telegram_bot_core/manage.py run_bot
   ```
The bot will be up and running!