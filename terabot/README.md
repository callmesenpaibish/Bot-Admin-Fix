# TeraBot — Modular Terabox Downloader Bot

A production-ready, fully asynchronous Telegram bot that resolves and streams Terabox download links. Built with Pyrogram, Motor (async MongoDB), and Pyromod.

## Project Structure

```
terabot/
├── main.py              # Entry point — starts the bot
├── config.py            # Loads env vars via python-dotenv
├── .env.template        # Copy to .env and fill in your values
├── requirements.txt
├── database/
│   ├── users_db.py      # User stats, premium status, daily limits
│   ├── admin_db.py      # Bot settings (forwarding, deltime, QR code, extra admins)
│   ├── plans_db.py      # Dynamic subscription plans
│   ├── fsc_db.py        # Force Sub Channels
│   └── cache_db.py      # Terabox link cache (with TTL)
├── plugins/
│   ├── user_panel.py    # /start, My Plan, Contact Us, reply keyboard
│   ├── admin_panel.py   # All admin commands
│   ├── payment_flow.py  # Plan selection + screenshot state (pyromod)
│   ├── fsub_handler.py  # Force subscription middleware
│   └── terabox.py       # Core download logic
└── utils/
    └── helpers.py       # Formatters, keyboard builders, auto-delete
```

## Setup

1. Copy `.env.template` to `.env` and fill in all values.
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python main.py`

## Admin Commands

| Command | Description |
|---|---|
| `/stats` | Total users, daily active, premium count, cache stats |
| `/broadcast` | Reply to a message to broadcast it to all users |
| `/addadmin <id>` | Add an extra admin |
| `/deladmin <id>` | Remove an extra admin |
| `/admins` | List all admins |
| `/addfsc <chat_id> [$joined\|$requested]` | Add force-sub channel |
| `/delfsc <chat_id>` | Remove force-sub channel |
| `/forwarding True\|False` | Enable/disable message forwarding |
| `/deltime <seconds>` | Auto-delete timer (0 to disable) |
| `/limituse <number>` | Set daily download limit for free users |
| `/addplan <name> <price> <days>` | Add a subscription plan |
| `/delplan <plan_id>` | Delete a subscription plan |
| `/plans` | List all active plans |
| `/setqr` | Reply to a photo to set the payment QR code |

## User Features

- `/start` — Welcome message with persistent reply keyboard
- **🔽 Download video** — Prompts user to send a Terabox link
- **👼 My plan** — Shows account status, plan, daily usage
- **📞 Contact us** — Support chat link
- **Check Plans** — Browse and purchase premium plans
- Force-sub gate — Required channel joins before using the bot
- Daily download limits for free users
- Smart link caching (1 hour TTL by default)
