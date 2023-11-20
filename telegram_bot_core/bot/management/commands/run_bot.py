from django.core.management import BaseCommand

from bot.main import bot


class Command(BaseCommand):
    help = 'Run bot'

    def handle(self, *args, **options):
        bot.run_polling()
