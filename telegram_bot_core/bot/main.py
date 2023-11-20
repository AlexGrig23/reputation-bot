from re import match, compile, findall
from collections import OrderedDict

from requests import get
from django.conf import settings
from django.db.models import Count, QuerySet
from django.template.loader import get_template
from django.core.exceptions import ObjectDoesNotExist

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CallbackContext
from telegram.ext import CommandHandler, MessageHandler, filters, CallbackQueryHandler

from asyncio import sleep, create_task
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import fitz
from io import BytesIO
from pyppeteer import launch
from PIL import Image, ImageFilter

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Side
from openpyxl.drawing.image import Image as PyxlImage

from bot.models import User, Group, Review
# from bot.speed_test import speed_test


# ----- Data Base ------------------------------------------------------------------------------------------------------

class DataBase:
    @staticmethod
    # @speed_test
    async def get_user_id_by_username(username) -> int:
        return User.objects.get(username=username).id

    @staticmethod
    # @speed_test
    async def get_user_object(user_id):
        return User.objects.filter(id=user_id).first()

    @staticmethod
    # @speed_test
    async def create_user(user_id, username) -> None:
        User.objects.create(id=user_id, username=username)

    @staticmethod
    # @speed_test
    async def update_user(user_id, username) -> None:
        User.objects.filter(id=user_id).update(username=username)

    @staticmethod
    # @speed_test
    async def get_avatar(context, user_id) -> str:
        avatar = await context.bot.getUserProfilePhotos(user_id)
        if avatar.total_count > 0:
            file_id = avatar.photos[0][0].file_id
            file = await context.bot.getFile(file_id)
            avatar_url = get(file.file_path).url
        else:
            avatar_url = None

        return avatar_url

    @staticmethod
    # @speed_test
    async def get_all_about_user(context, user_id):
        user = await db.get_user_object(user_id)
        avatar_url = await db.get_avatar(context, user_id)
        member = await context.bot.get_chat_member(user_id, user_id)

        user.first_name = member.user.first_name
        user.last_name = member.user.last_name
        user.full_name = member.user.full_name
        user.username = member.user.name
        user.avatar_url = avatar_url

        return user

    @staticmethod
    # @speed_test
    async def get_list_of_members(group_id) -> QuerySet:
        users = (Review.objects.filter(group_id=group_id).values('to_user').annotate(Count('to_user')))
        return User.objects.filter(id__in=[user['to_user'] for user in users])

    @staticmethod
    # @speed_test
    async def get_group_object(group_id) -> Group:
        return Group.objects.filter(id=group_id).first()

    @staticmethod
    # @speed_test
    async def get_group_name(context, group_id) -> str:
        group = await context.bot.get_chat(group_id)
        return group.title

    @staticmethod
    # @speed_test
    async def create_group(group_id, name, admin) -> None:
        Group.objects.create(id=group_id, name=name, admin=admin)

    @staticmethod
    # @speed_test
    async def update_group(group_id, name) -> None:
        Group.objects.filter(id=group_id).update(name=name)

    @staticmethod
    # @speed_test
    async def get_list_of_groups(user_id) -> QuerySet:
        return Group.objects.filter(admin_id=user_id)

    @staticmethod
    # @speed_test
    async def create_review(message_id, message, from_user, group, to_user) -> None:
        Review(id=message_id, description=message, karma=1, from_user=from_user, group=group, to_user=to_user).save()

    @staticmethod
    # @speed_test
    async def update_review(update, message) -> None:
        message_id = update.edited_message.id

        try:
            review = Review.objects.get(id=message_id)
            review.description = message
            review.save()

        except ObjectDoesNotExist:
            from_user_id = update.edited_message.from_user.id
            group_id = update.edited_message.chat_id
            to_user_id = update.edited_message.reply_to_message.from_user.id

            await db.add_review(message_id, message, from_user_id, group_id, to_user_id)

    @staticmethod
    # @speed_test
    async def delete_review(update) -> None:
        message_id = update.edited_message.id
        review = Review.objects.get(id=message_id)
        review.delete()

    @staticmethod
    # @speed_test
    async def get_statistic(start_date, end_date, group_id, user, file=False):
        statistic = Review.objects.filter(
            group_id=group_id, to_user=user.id,
            created_at__gte=start_date, created_at__lte=end_date
        ).order_by('-created_at', '-id')

        karma_count = sum([review.karma for review in statistic])
        total_karma = Review.objects.filter(group_id=group_id, to_user=user.id).values('karma')
        total_karma_count = sum([info['karma'] for info in total_karma])

        user.karma_count = karma_count
        user.total_karma_count = total_karma_count

        # convert dates for django filters in templates
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')

        user.start_date = start_date_obj
        user.end_date = end_date_obj

        if file:
            return statistic, user

        return statistic[:15], user

    @staticmethod
    # @speed_test
    async def get_top_members(context, group_id) -> list:
        users = Review.objects.filter(
            group_id=group_id).values('to_user').annotate(count=Count('to_user'))[:10]

        user_ids = [info['to_user'] for info in users]
        users_data = [await db.get_all_about_user(context, user_id) for user_id in user_ids]

        position = {}
        for user in users_data:
            start_date, end_date = await db.get_first_review(user.id, group_id)
            await db.get_statistic(start_date, end_date, group_id, user)
            position.update({user.total_karma_count: user})

        rating = 1
        sorted_users_data = []
        sorted_positions = OrderedDict(sorted(position.items(), reverse=True))
        for key, user in sorted_positions.items():
            sorted_users_data.append(user)
            user.rating = rating
            rating += 1

        return sorted_users_data

    @staticmethod
    # @speed_test
    async def get_first_review(user_id, group_id) -> tuple[str, str]:
        first_review = (
            Review.objects.filter(group_id=group_id, to_user=user_id)
            .annotate(Count('created_at'))
            .order_by('created_at').first()
        )

        today = datetime.today()
        start_date = first_review.created_at.strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')

        return start_date, end_date

    @staticmethod
    # @speed_test
    async def check_message(message) -> bool:
        for i in dictionary:
            if i in message.lower():
                return True

        return False

    @staticmethod
    # @speed_test
    async def check_admin(update, context) -> tuple[bool, int]:
        user_id = update.message.from_user.id
        chat_id = update.message.chat_id

        user = await context.bot.get_chat_member(chat_id, user_id)
        admin = True if user.status in ["administrator", "creator"] else False

        return admin, user_id

    @staticmethod
    # @speed_test
    async def add_review(message_id, message, from_user_id, group_id, to_user_id) -> None:
        group = await db.get_group_object(group_id)
        to_user = await db.get_user_object(to_user_id)
        from_user = await db.get_user_object(from_user_id)

        await db.create_review(message_id, message, from_user, group, to_user)

    @staticmethod
    # @speed_test
    async def check_or_add_user(update) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.name
        user = await db.get_user_object(user_id)

        if user:
            if user.username != username:
                await db.update_user(user_id, username)
        else:
            await db.create_user(user_id, username)

    @staticmethod
    # @speed_test
    async def check_or_add_group(update, context) -> int:
        group_id = update.effective_chat.id
        title = update.effective_chat.title
        group = await db.get_group_object(group_id)

        if group:
            if group.name != title:
                await db.update_group(group_id, title)
        else:
            admin = await db.get_chat_admin(update, context)
            await db.create_group(group_id, title, admin)

        return group_id

    @staticmethod
    # @speed_test
    async def message_info(update, replay):
        from_user, from_user_id = await db.get_username_and_user_id(update.message.from_user)
        message_id = update.message.id

        if replay:
            to_user, to_user_id = await db.get_username_and_user_id(update.message.reply_to_message.from_user)
            message = update.message.text

        else:  # if a message addressed to user
            slicer = 1 if '@' in update.message.text_html else 2
            to_user, to_user_id = await db.get_username_and_user_id(' '.join(update.message.text_html.split()[:slicer]))
            message = ' '.join(update.message.text_html.split()[slicer:])

        return to_user, to_user_id, from_user, from_user_id, message, message_id

    @staticmethod
    # @speed_test
    async def get_username_and_user_id(user) -> tuple[str, int]:
        if isinstance(user, str):
            username = user
            user_id = await db.get_user_id_by_username(username)
        else:
            username = f'<a href="tg://user?id={user.id}">{user.name}</a>' if "@" not in user.name else user.name
            user_id = user.id

        return username, user_id

    @staticmethod
    # @speed_test
    async def get_chat_admin(update, context) -> QuerySet:
        chat_id = update.message.chat_id
        members = await context.bot.get_chat_administrators(chat_id)

        for member in members:
            if member.status == "creator":
                return await db.get_user_object(member.user.id)


# ----- Dates ----------------------------------------------------------------------------------------------------------


class Date:
    @staticmethod
    # @speed_test
    async def get_month() -> tuple[str, str]:
        today = datetime.today()
        month = today.month

        month_start = today.replace(month=month, day=1)
        month_end = month_start + relativedelta(months=1) - timedelta(days=1)

        month_start = month_start.strftime('%Y-%m-%d')
        month_end = month_end.strftime('%Y-%m-%d')

        return month_start, month_end

    @staticmethod
    # @speed_test
    async def get_previous_month(period) -> tuple[str, str]:
        year, month, day = period.split("-")

        today = datetime.today()
        month_start = today.replace(year=int(year), month=int(month), day=1) - relativedelta(months=1)
        month_end = month_start + relativedelta(months=1) - timedelta(days=1)

        month_start = month_start.strftime('%Y-%m-%d')
        month_end = month_end.strftime('%Y-%m-%d')

        return month_start, month_end

    @staticmethod
    # @speed_test
    async def get_quarter() -> tuple[str, str, int]:
        today = datetime.today()
        quarter_index = (today.month - 1) // 3
        month = quarter_index * 3 + 1

        quarter_start = today.replace(month=month, day=1)
        quarter_end = quarter_start + relativedelta(months=3) - timedelta(days=1)

        quarter_start = quarter_start.strftime('%Y-%m-%d')
        quarter_end = quarter_end.strftime('%Y-%m-%d')
        quarter = quarter_index + 1

        return quarter_start, quarter_end, quarter

    @staticmethod
    # @speed_test
    async def get_previous_quarter(period) -> tuple[str, str]:
        year, month, day = period.split("-")
        today = datetime.today()

        quarter_start = today.replace(year=int(year), month=int(month), day=1) - relativedelta(months=3)
        quarter_end = quarter_start + relativedelta(months=3) - timedelta(days=1)

        quarter_start = quarter_start.strftime('%Y-%m-%d')
        quarter_end = quarter_end.strftime('%Y-%m-%d')

        return quarter_start, quarter_end

    @staticmethod
    # @speed_test
    async def get_year() -> tuple[str, str]:
        today = datetime.today()
        year = today.year

        year_start = today.replace(year=year, month=1, day=1)
        year_end = year_start + relativedelta(years=1) - timedelta(days=1)

        year_start = year_start.strftime('%Y-%m-%d')
        year_end = year_end.strftime('%Y-%m-%d')

        return year_start, year_end

    @staticmethod
    # @speed_test
    async def get_previous_year(period) -> tuple[str, str]:
        year, month, day = period.split("-")
        today = datetime.today()

        year_start = today.replace(year=int(year), month=1, day=1) - relativedelta(years=1)
        year_end = year_start + relativedelta(years=1) - timedelta(days=1)

        year_start = year_start.strftime('%Y-%m-%d')
        year_end = year_end.strftime('%Y-%m-%d')
        return year_start, year_end

    @staticmethod
    # @speed_test
    async def encoder(data, encrypt=None) -> tuple[str, str] | str:
        if encrypt:
            start_date, end_date = data
            byte = start_date.split("-")
            byte.extend(end_date.split("-"))
            encrypted_dates = "".join(byte)
            return encrypted_dates
        else:
            first, second = data[:8], data[8:]
            f_year, f_month, f_day = first[:4], first[4:6], first[6:]
            s_year, s_month, s_day = second[:4], second[4:6], second[6:]
            f_date = f"{f_year}-{f_month}-{f_day}"
            s_date = f"{s_year}-{s_month}-{s_day}"
            return f_date, s_date

    @staticmethod
    # @speed_test
    async def normal_view(start_date, end_date=None) -> tuple[str, str] | str:
        s_year, s_month, s_day = start_date.split("-")
        new_start_date = f"{s_day}.{s_month}.{s_year}"

        if end_date:
            e_year, e_month, e_day = end_date.split("-")
            new_end_date = f"{e_day}.{e_month}.{e_year}"
            return new_start_date, new_end_date

        return new_start_date


# ----- Browser --------------------------------------------------------------------------------------------------------


class Browser:
    browser = None
    close_browser_task = None

    @classmethod
    # @speed_test
    async def initialize_browser(cls) -> None:
        if cls.browser is None:
            cls.browser = await launch()
            cls.schedule_close_browser()

    @classmethod
    def schedule_close_browser(cls) -> None:
        if cls.close_browser_task:
            cls.close_browser_task.cancel()

        cls.close_browser_task = create_task(cls.close_browser_after_timeout())

    @classmethod
    async def close_browser_after_timeout(cls) -> None:
        await sleep(30)
        await cls.close_browser()

    @classmethod
    async def close_browser(cls) -> None:
        if cls.browser is not None:
            await cls.browser.close()
            cls.browser = None


# ----- Generators -----------------------------------------------------------------------------------------------------


class ImageGenerator:
    @staticmethod
    # @speed_test
    async def member_statistic(context, start_date, end_date, group_id, user_id) -> bytes:
        user = await db.get_all_about_user(context, user_id)
        render_statistic, user = await db.get_statistic(start_date, end_date, group_id, user)

        context = {"statistic": render_statistic, "user": user}
        template = get_template("member_statistic.html")
        html_code = template.render(context)

        return await generate.png_from_html(html_code)  # convert HTML to PNG bytes

    @staticmethod
    # @speed_test
    async def top_members(context, group_id) -> bytes:
        statistic = await db.get_top_members(context, group_id)
        context = {"statistic": statistic}

        template = get_template("top_members.html")
        html_code = template.render(context)

        return await generate.png_from_html(html_code)  # convert HTML to PNG bytes

    @staticmethod
    # @speed_test
    async def png_from_html(html_content) -> bytes:
        await Browser.initialize_browser()
        page = await Browser.browser.newPage()

        await page.setContent(html_content)  # read HTML
        await generate.are_images_loaded(page)  # check if images loaded
        await generate.add_css_styles(page, "bot.css")  # add CSS styles
        await generate.set_page_size(page)  # change page size
        screenshot = await page.screenshot()  # get screenshot bytes

        await page.close()
        return await generate.enhance_img(screenshot)

    @staticmethod
    # @speed_test
    async def set_page_size(page) -> None:
        with open(settings.JS / "get_div_size.js", encoding="utf-8") as js_script:
            template = js_script.read()
            size = await page.evaluate(template)
            await page.setViewport(size)

    @staticmethod
    # @speed_test
    async def add_css_styles(page, template_name) -> None:
        with open(settings.CSS / template_name, encoding="utf-8") as css_file:
            template = css_file.read()
            await page.addStyleTag(content=template)

    @staticmethod
    # @speed_test
    async def are_images_loaded(page) -> None:
        # resource loading handler
        def on_response(response):
            request = response.request
            if request.resourceType in ['image', 'media', 'font', 'stylesheet']:
                response.buffer()

        page.on('response', on_response)

        with open(settings.JS / "checkImages.js", encoding="utf-8") as js_script:
            template = js_script.read()
            await page.evaluate(template)

            # waiting to upload images
            for _ in range(500):
                are_images_loaded = await page.evaluate(template)
                if are_images_loaded:
                    break
                await sleep(0.01)

    @staticmethod
    # @speed_test
    async def enhance_img(png_data) -> bytes:
        pdf_document = fitz.open(stream=png_data, filetype="pdf")
        page = pdf_document[0]
        image = page.get_pixmap()

        img = Image.frombytes("RGB", (image.width, image.height), image.samples)
        img_sharp = img.filter(ImageFilter.SHARPEN)

        with BytesIO() as png_data:
            img_sharp.save(png_data, format="PNG", compress_level=0)
            return png_data.getvalue()


class ExelGenerator:
    @staticmethod
    # @speed_test
    async def gen_profile_table(sheet, user, alignment_1, alignment_2) -> None:
        row = {}
        await exel.add_image_to_cell(sheet, user.avatar_url, 'A1:A3') if user.avatar_url else None
        row.update({'B1:C2': {'data': user.full_name, 'alignment': alignment_2}}) if user.full_name else None
        row.update({'B3:C3': {'data': user.username, 'alignment': alignment_2}}) if user.username else None
        row.update({'D3': {'data': user.karma_count, 'alignment': alignment_1}}) if user.karma_count else 0
        row.update({'E3': {'data': user.total_karma_count, 'alignment': alignment_1}}) if user.total_karma_count else 0

        await exel.add_row_in_table(row, sheet)

    @staticmethod
    # @speed_test
    async def gen_statistic_table(sheet, statistic, start_date, end_date, alignment_1, alignment_2) -> None:
        col_number = 7
        for field in statistic:
            created_at = await date.normal_view(str(field.created_at))
            username = field.from_user.username
            karma = field.karma
            description = field.description
            group_name = field.group.name

            # Вираховуємо висоту рядка на основі максимальної довжини тексту
            max_text_length = max(len(description), len(group_name))

            row_height = 15.75
            multiples = max_text_length // 30
            row_height += 15.75 * multiples

            sheet.row_dimensions[col_number].height = row_height

            row = {
                f'A5:E5': {'data': f'{start_date} — {end_date}', 'alignment': alignment_2},
                f'A{col_number}': {'data': username, 'alignment': alignment_1},
                f'B{col_number}': {'data': karma, 'alignment': alignment_1},
                f'C{col_number}': {'data': description, 'alignment': alignment_2},
                f'D{col_number}': {'data': group_name, 'alignment': alignment_1},
                f'E{col_number}': {'data': created_at, 'alignment': alignment_1}
            }
            col_number += 1

            await exel.add_row_in_table(row, sheet)

    @staticmethod
    # @speed_test
    async def add_image_to_cell(sheet, image_url, cell_address, width=125, height=125) -> None:
        cell = sheet[cell_address.split(":")[0]]

        response = get(image_url)
        image_data = BytesIO(response.content)

        img = PyxlImage(image_data)
        img.width = width
        img.height = height
        sheet.add_image(img, cell.coordinate)

    @staticmethod
    # @speed_test
    async def add_row_in_table(row, sheet) -> None:
        for cell_address, properties in row.items():
            cell = sheet[cell_address.split(":")[0]]
            cell.value = properties['data']
            cell.alignment = properties['alignment']
            border = Side(border_style='thin', color='000000')
            cell.border = Border(left=border, right=border, top=border, bottom=border)


# ----- InlineKeyboards ------------------------------------------------------------------------------------------------

class InlineKeyboard:
    @staticmethod
    # @speed_test
    async def select_group(update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        data = query.data.split(":")
        command = data[0]
        group_id = data[1]

        chat_id = query.message.chat_id
        list_of_members = await db.get_list_of_members(group_id)
        group_name = await db.get_group_name(context, group_id)

        if list_of_members:
            if command == "/member":
                text = f"<b>{group_name}</b>\nОберіть користувача:"
                await query.edit_message_text(text, parse_mode="HTML")

                message_id = query.message.message_id
                reply_markup = await inline_kb.gen_members_reply_markup(list_of_members, group_id)
                await context.bot.editMessageReplyMarkup(chat_id, message_id, reply_markup=reply_markup)

            if command == "/top":
                file_output = await generate.top_members(context, group_id)
                await context.bot.send_photo(chat_id=chat_id, photo=InputFile(file_output))

        else:
            text = f'В "<b>{group_name}</b>" поки немає жодного запису!'
            message = await context.bot.send_message(chat_id, text, parse_mode="HTML")
            await sleep(3)
            await context.bot.delete_message(chat_id, message.id)

    @staticmethod
    # @speed_test
    async def gen_members_reply_markup(list_of_members, group_id) -> InlineKeyboardMarkup:
        row_buttons = []
        keyboard = []

        for index, member in enumerate(list_of_members):
            callback_data = f"sel_m:{member.id}:{group_id}"
            keyboard_button = InlineKeyboardButton(member.username, callback_data=callback_data)
            row_buttons.append(keyboard_button)

            if len(row_buttons) == 2 or index == len(list_of_members) - 1:
                keyboard.append(row_buttons.copy())
                row_buttons.clear()

        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    # @speed_test
    async def gen_period_reply_markup(user_id, group_id) -> InlineKeyboardMarkup:
        row_buttons = []
        keyboard = []
        buttons_dict = {"M": "Місяць", "Q": "Квартал", "Y": "Рік", "A": "За весь період"}

        for index, (key, value) in enumerate(buttons_dict.items()):
            keyboard_button = InlineKeyboardButton(value, callback_data=f"sel=p:{key}:{user_id}:{group_id}")
            row_buttons.append(keyboard_button)

            if len(row_buttons) == 3 or index == len(buttons_dict) - 1:
                keyboard.append(row_buttons.copy())
                row_buttons.clear()

        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    # @speed_test
    async def select_member(update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        data = query.data.split(":")
        user_id = data[1]
        group_id = data[2]

        user = await db.get_user_object(user_id)
        text = f"Статистика для {user.username} за:"
        await query.edit_message_text(text, parse_mode="HTML")

        chat_id = query.message.chat_id
        message_id = query.message.message_id
        reply_markup = await inline_kb.gen_period_reply_markup(user_id, group_id)
        await context.bot.editMessageReplyMarkup(chat_id, message_id, reply_markup=reply_markup)

    @staticmethod
    # @speed_test
    async def select_period(update: Update, context: CallbackContext, start_date=None, end_date=None) -> None:
        query = update.callback_query

        data = query.data.split(":")
        action = data[0]
        period_name = data[1]
        user_id = data[2]
        group_id = data[3]
        user = await db.get_user_object(user_id)
        user_name = user.username

        chat_id = query.message.chat_id
        message_id = query.message.message_id

        if action == "sel-p":
            encrypted_dates = data[4]
            callback_data = f"exel:{encrypted_dates}:{group_id}:{user_id}:{message_id}"
            keyboard = [[InlineKeyboardButton("Згенерувати файл Exel", callback_data=callback_data)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.editMessageReplyMarkup(chat_id, message_id, reply_markup=reply_markup)

        if start_date is None and period_name != "A":
            if period_name == "M":
                start_date, end_date = await date.get_month()

            elif period_name == "Q":
                start_date, end_date, quarter = await date.get_quarter()

            elif period_name == "Y":
                start_date, end_date = await date.get_year()

        button_name_dict = {"M": "місяць", "Q": "квартал", "Y": "рік", "A": "весь період"}
        button_name = f"Переглянути попередній {button_name_dict[period_name]}"

        if period_name == "A":
            button_name = None
            start_date, end_date = await db.get_first_review(user_id, group_id)

        keyboard = []
        encrypted_dates = await date.encoder((start_date, end_date), True)
        callback_data = f"exel:{encrypted_dates}:{group_id}:{user_id}:{message_id}"
        keyboard_button = [InlineKeyboardButton("Згенерувати файл Exel", callback_data=callback_data)]
        keyboard.append(keyboard_button)

        if button_name is not None:
            callback_data = f"sel-p:{period_name}:{user_id}:{group_id}:{encrypted_dates}"
            keyboard_button = [InlineKeyboardButton(button_name, callback_data=callback_data)]
            keyboard.append(keyboard_button)

        file_output = await generate.member_statistic(context, start_date, end_date, group_id, user_id)

        reply_markup = InlineKeyboardMarkup(keyboard)
        start_date, end_date = await date.normal_view(start_date, end_date)
        text = f"Статистика для {user_name} \nз {start_date} — {end_date}"
        await context.bot.send_photo(chat_id=chat_id, photo=InputFile(file_output))
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup)

    @staticmethod
    # @speed_test
    async def select_previous_period(update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        data = query.data.split(":")
        period_name = data[1]
        encrypted_dates = data[4]

        start_date, end_date = await date.encoder(encrypted_dates)

        if period_name == "M":
            start_date, end_date = await date.get_previous_month(start_date)
        elif period_name == "Q":
            start_date, end_date = await date.get_previous_quarter(start_date)
        elif period_name == "Y":
            start_date, end_date = await date.get_previous_year(start_date)

        await inline_kb.select_period(update, context, start_date, end_date)

    @staticmethod
    # @speed_test
    async def generate_exel_file(update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        data = query.data.split(":")

        encrypted_dates = data[1]
        group_id = data[2]
        user_id = data[3]

        user = await db.get_all_about_user(context, user_id)
        start_date, end_date = await date.encoder(encrypted_dates)
        statistic, user = await db.get_statistic(start_date, end_date, group_id, user, file=True)

        file_name = "member_statistic.xlsx"
        template_path = settings.EXEL_TEMPLATES / file_name
        wb = load_workbook(template_path)
        sheet = wb.active

        alignment_1 = Alignment(horizontal='center', vertical='center', wrap_text=True)
        alignment_2 = Alignment(horizontal='left', vertical='center', wrap_text=True)

        start_date, end_date = await date.normal_view(start_date, end_date)
        await exel.gen_profile_table(sheet, user, alignment_1, alignment_2)
        await exel.gen_statistic_table(sheet, statistic, start_date, end_date, alignment_1, alignment_2)

        output_buffer = BytesIO()
        wb.save(output_buffer)
        output_buffer.seek(0)

        username = user.username
        chat_id = update.effective_chat.id
        file_name = f'{start_date} - {end_date}, {username}.xlsx'
        await context.bot.send_document(chat_id, InputFile(output_buffer, file_name))


# ----- Handlers -------------------------------------------------------------------------------------------------------

class Handler:
    @staticmethod
    # @speed_test
    async def start(update: Update, context: CallbackContext) -> None:
        user_id = update.effective_user.id

        # create a user if it does not exist in the database
        if not await db.get_user_object(user_id):
            username = update.effective_user.name
            await db.create_user(user_id, username)

        send_message = context.bot.send_message
        if update.effective_chat.type == 'private':
            await send_message(
                user_id,
                f"<b>Доступні команди:</b>\n\n"

                f"<b>Технічні:</b>\n"
                f"/help - переглянути команди\n\n"
                # f"/support - зв'язатись з підтримкою *\n\n"

                f"<b>Статистика:</b>\n"
                f"/top - рейтинг учасників\n"
                f"/member - статистика учасника",
                parse_mode="HTML")
        else:
            await update.message.delete()
            await send_message(user_id, f"Привіт! Цей бот не виконує команди у групах")

    @staticmethod
    # @speed_test
    async def groups(update: Update, context: CallbackContext) -> None:
        user_id = update.message.from_user.id
        if update.effective_chat.type == 'private':
            await Browser.initialize_browser()
            send_message = context.bot.send_message
            groups_query = await db.get_list_of_groups(user_id)
            command = update.message.text  # /top, /member

            if groups_query:
                keyboard = []
                for group in groups_query:
                    keyboard_button = InlineKeyboardButton(group.name, callback_data=f"{command}:{group.id}")
                    keyboard.append([keyboard_button])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await send_message(user_id, "Оберіть групу:", reply_markup=reply_markup)

            else:
                await send_message(user_id, f"Поки немає жодного запису!")

        else:
            await update.message.delete()
            await context.bot.send_message(user_id, f"Привіт! Цей бот не виконує команди у групах")

    @staticmethod
    # @speed_test
    async def message_handler(update: Update, context: CallbackContext) -> None:
        pattern_1 = r'.*?@.*'  # if user have username
        pattern_2 = r'<a\s+href="tg://user\?id=\d+">.*?</a>.*'  # if user doesn't have username
        patterns = [pattern_1, pattern_2]

        edited_message = bool(update.edited_message)
        message = update.edited_message.text if edited_message else update.message.text_html
        patterns_match = True if any(match(pattern, message) for pattern in patterns) else False

        reply = False if edited_message else update.message.reply_to_message
        reply_to_me = True if reply and reply.from_user.id == update.effective_user.id else False
        await db.check_or_add_user(update)

        if patterns_match or reply and reply_to_me is False:
            to_user, to_user_id, from_user, from_user_id, message, message_id = await db.message_info(update, reply)

            massage_to_bot = True if findall('_bot$', to_user) else False
            is_message_good = await db.check_message(message) if massage_to_bot is False else False

            if is_message_good:
                send_message = context.bot.send_message
                group_id = await db.check_or_add_group(update, context)
                text = f"<b><i>{to_user} +1 в карму \nвід {from_user}</i></b>"

                await send_message(group_id, text, parse_mode="HTML")
                await db.add_review(message_id, message, from_user_id, group_id, to_user_id)

        if edited_message:
            is_message_good = await db.check_message(message)

            if is_message_good:
                await db.update_review(update, message)
            else:
                await db.delete_review(update)


date = Date()
db = DataBase()
handle = Handler()
exel = ExelGenerator()
generate = ImageGenerator()
inline_kb = InlineKeyboard()

bot = ApplicationBuilder().token(settings.TOKEN_BOT).build()
bot.add_handler(CommandHandler(["start", "help"], handle.start))
bot.add_handler(CommandHandler(["member", "top"], handle.groups))
bot.add_handler(MessageHandler(filters.TEXT | filters.REPLY, handle.message_handler))

bot.add_handler(CallbackQueryHandler(inline_kb.select_group, pattern=compile(r'^/(member|top):')))
bot.add_handler(CallbackQueryHandler(inline_kb.select_member, pattern='^sel_m:'))
bot.add_handler(CallbackQueryHandler(inline_kb.select_period, pattern='^sel=p:'))
bot.add_handler(CallbackQueryHandler(inline_kb.select_previous_period, pattern='^sel-p:'))
bot.add_handler(CallbackQueryHandler(inline_kb.generate_exel_file, pattern='^exel:'))

dictionary = [
    # reactions
    "👍", "👌", "💪", "🫶", "👏", "🔥", "❤️", "+",

    # ru
    "спасибо", "большое спасибо", "хорошая работа", "хорошо", "молодец", "супер", "замечательно", "прекрасно",
    "чудесно", "великолепно"

    # ua
    "дякую", "велике дякую", "дуже дякую", "велика подяка", "спасибі", "велике спасибі", "гарна робота", "добре",
    "молодець", "супер", "чудово", "прекрасно",

    # en
    "thank you", "thank you very match", "thanks", "great thanks", "big thank you", "big thanks", "good", "good work",
    "nice", "beautiful",
]

# ----------------------------------------------------------------------------------------------------------------------
