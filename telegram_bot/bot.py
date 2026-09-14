import logging
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram import BotCommand
from telegram.constants import ParseMode
import config
from telegram_bot.handlers import (
    start_command,
    menu_command,
    status_command,
    button_callback,
    text_message_handler,
    set_components,
)

logger = logging.getLogger("TelegramBot")


class ManagementBot:
    """
    Telegram bot for managing the MT5 execution system.
    Provides a menu-driven interface for full control.
    """

    def __init__(self, mt5_connector, trade_executor):
        self.mt5 = mt5_connector
        self.executor = trade_executor
        self.app = None
        self._notify_chat_id = config.TELEGRAM_ADMIN_ID

        # Share components with handlers module
        set_components(mt5_connector, trade_executor)

    async def start(self):
        """Build and start the Telegram bot."""
        self.app = (
            Application.builder()
            .token(config.TELEGRAM_BOT_TOKEN)
            .build()
        )

        # Register command handlers
        self.app.add_handler(CommandHandler("start", start_command))
        self.app.add_handler(CommandHandler("menu", menu_command))
        self.app.add_handler(CommandHandler("status", status_command))

        # Register callback query handler for inline buttons
        self.app.add_handler(CallbackQueryHandler(button_callback))

        # Register text message handler (for settings input)
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message_handler,
        ))

        # Initialize and start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

        # Register persistent bot menu commands
        await self.app.bot.set_my_commands([
            BotCommand("menu", "Open the control panel"),
            BotCommand("status", "Quick system status"),
            BotCommand("start", "Welcome & restart"),
        ])

        logger.info("🤖 Telegram Management Bot is LIVE!")

        # Send startup notification
        await self.send_notification(
            "🚀 *System Online!*\n\n"
            "Your MT5 Private Execution System has started.\n"
            "🎮 Use /menu to open the control panel.\n\n"
            "💎 Let's make it happen, Champion! ✨"
        )

    async def send_notification(self, text: str):
        """Send a notification message to the admin."""
        if self.app and self._notify_chat_id:
            try:
                await self.app.bot.send_message(
                    chat_id=self._notify_chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

    async def stop(self):
        """Stop the Telegram bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("🤖 Telegram bot stopped")
