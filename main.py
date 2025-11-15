import json 
import sqlite3
import io
import logging 
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
) 
from telegram.error import TimedOut, NetworkError 

# ----------------------------------------------------
# 🌟 التعديل هنا: استيراد بيانات الطوابق
from floor1_data import FLOOR_1_DATA
from floor2_data import FLOOR_2_DATA
# ----------------------------------------------------

# تفعيل التسجيل (للتتبع في الخلفية)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING 
)

# ====================================================================
#              1. الإعدادات والثوابت
# ====================================================================

TOKEN = '7868200495:AAF5Xclp7yLOJJUzBP9qk3ZVqI1khO432VE'
DB_NAME = 'housing_complex.db' 
HOUSING_DATA_FILE = 'housing_data.json' 
MONTHLY_FEE = 25000 
AUTHORIZED_IDS = [7769271031, 758818091, 6070590064]
PAYMENT_AMOUNTS = [5000, 10000, 15000, 20000, 25000] 
CONFIRM_RESET_PHRASE = "نعم" 
# زيادة المهلة الزمنية للتعامل مع مشاكل الشبكة في Pydroid3
DEFAULT_TIMEOUT = 90.0 

housing_data = {} 

# ====================================================================
#              2. دوال معالجة البيانات (JSON) - تم التحديث
# ====================================================================

def save_housing_data():
    """حفظ البيانات من المتغير العالمي إلى ملف JSON."""
    global housing_data
    try:
        with open(HOUSING_DATA_FILE, 'w', encoding='utf-8') as f:
            # استخدام ensure_ascii=False لحفظ الأحرف العربية بشكل صحيح
            json.dump(housing_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ خطأ في حفظ ملف JSON: {e}")

def _initial_data_load_and_merge():
    """تحميل البيانات الأولية ودمجها من ملفات Python."""
    print("⚠️ لا توجد بيانات. يتم تحميل ودمج البيانات الأولية من ملفات Python...")
    
    all_data = []
    
    # 1. إضافة بيانات الطابق الأول (1-85)
    all_data.extend(FLOOR_1_DATA)
    
    # 2. إضافة بيانات الطابق الثاني (1-85)
    all_data.extend(FLOOR_2_DATA)
    
    data_dict = {}
    for row in all_data:
        house_number, owner_name, phone_number, floor, branch_number = row
        
        # استخدام مفتاح مركب (رقم الطابق + رقم الدار)
        # هذا يضمن عدم تداخل البيوت (1/1 للدار رقم 1 في الطابق 1، و 2/1 للدار رقم 1 في الطابق 2)
        unique_key = f"{floor}-{house_number}" 
        
        data_dict[unique_key] = {
            "house_number": house_number,
            "owner_name": owner_name,
            "phone_number": phone_number,
            "floor": floor,
            "branch_number": branch_number,
            "paid_amount": 0 # يبدأ التسديد بصفر
        }
    
    print(f"✅ تم دمج {len(data_dict)} سجل من ملفات البيانات الأولية بنجاح.")
    return data_dict

def load_housing_data():
    """تحميل البيانات من JSON أو إنشائها من ملفات Python إذا لم يكن ملف JSON موجوداً."""
    global housing_data
    try:
        # 1. محاولة التحميل من ملف JSON
        with open(HOUSING_DATA_FILE, 'r', encoding='utf-8') as f:
            housing_data = json.load(f)
        print(f"✅ تم تحميل البيانات من {HOUSING_DATA_FILE} بنجاح.")
    except (FileNotFoundError, json.JSONDecodeError):
        # 2. إذا فشل التحميل، يتم إنشاء البيانات من ملفات Python وحفظها كـ JSON
        housing_data = _initial_data_load_and_merge()
        if housing_data:
            save_housing_data() 
        else:
            print("⚠️ لا توجد بيانات للتحميل. البوت سيعمل بقائمة فارغة.")
            housing_data = {}

# ====================================================================
#              3. معالج الأخطاء العام
# ====================================================================

async def error_handler(update: object, context) -> None:
    """يسجل الخطأ ويحاول إبلاغ المستخدم (إذا أمكن)."""
    # تسجيل الخطأ
    logging.warning('❌ Update "%s" caused error "%s"', update, context.error)

    # محاولة إبلاغ المستخدم
    if isinstance(update, Update) and update.effective_chat:
        try:
            error_message = str(context.error)
            # التعامل مع أخطاء الشبكة والمهلة الزمنية
            if isinstance(context.error, (TimedOut, NetworkError)) or "ReadTimeout" in error_message or "ConnectTimeout" in error_message:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ **خطأ في الشبكة/المهلة الزمنية:** حدث تأخير في الاستجابة من تليجرام. يرجى المحاولة مرة أخرى فوراً.",
                    parse_mode='Markdown'
                )
            # تجاهل خطأ (Query is too old) لأنه يحدث بسبب تأخير في البوت أو ضغط المستخدم على زر قديم
            elif "Query is too old" in error_message:
                 pass
            else:
                 # في حالة الأخطاء الأخرى نرسل رسالة عامة
                 await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ **حدث خطأ غير متوقع.** تم تسجيل المشكلة.",
                    parse_mode='Markdown'
                 )
        except Exception:
            # تجنب تعطل معالج الأخطاء نفسه
            pass


# ====================================================================
#              4. دوال واجهة البوت والأوامر (Async)
# ====================================================================

def is_authorized(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم ضمن قائمة الأشخاص المخولين."""
    return user_id in AUTHORIZED_IDS

async def start(update: Update, context) -> None: 
    user_id = update.effective_user.id
    
    # التأكد من إزالة أي حالة انتظار ملف استرجاع عند بدء تشغيل جديد
    context.user_data.pop('awaiting_restore_file', None) 
    
    if not is_authorized(user_id):
        if update.message: await update.message.reply_text("عذراً، لا تملك صلاحية الوصول لهذا البوت.")
        return

    keyboard = [
        [InlineKeyboardButton("🏠 الطابق الأول (1)", callback_data='MAIN_FLOOR_1'), InlineKeyboardButton("🏢 الطابق الثاني (2)", callback_data='MAIN_FLOOR_2')],
        [InlineKeyboardButton("🔍 بحث عن دار", callback_data='MAIN_SEARCH')], 
        [InlineKeyboardButton("📊 الإحصائيات", callback_data='MAIN_STATS')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = 'أهلاً بك في نظام جرد رسوم المجمع السكني.\nالرجاء اختيار أحد الأوامر:'
    
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)


async def handle_query(update: Update, context) -> None:
    query = update.callback_query
    # أهم خطوة: الرد على الكويري فوراً لتجنب خطأ "Query is too old"
    await query.answer() 
    data = query.data.split('_') 

    user_id = query.from_user.id
    if not is_authorized(user_id):
        await query.edit_message_text("❌ لا تملك صلاحية.")
        return
        
    # التأكد من إزالة أي حالة انتظار ملف استرجاع عند استخدام الأزرار
    context.user_data.pop('awaiting_restore_file', None) 

    if data[0] == 'START': await start(update, context)
    elif data[0] == 'MAIN':
        if data[1] == 'FLOOR': await show_branches(query, data[2])
        elif data[1] == 'STATS': await show_stats_menu(query)
        elif data[1] == 'SEARCH': 
            await query.edit_message_text("الرجاء إرسال **رقم الدار (حصراً)** أو **اسم الساكن** للبحث الدقيق:", parse_mode='Markdown')
            
    elif data[0] == 'BRANCH': 
        await show_branch_houses(query, data[1], data[2], update.effective_chat.id, context) 
    
    # تمرير مفتاح الدار الفريد (Floor-HouseNumber) في البايلود
    elif data[0] == 'PAY': 
        # HouseKey يكون على شكل: 1-5 (للطابق الأول، الدار رقم 5)
        await prompt_payment_amount(query, data[1])
    
    # استخدام مفتاح الدار الفريد في تسجيل المبلغ
    elif data[0] == 'AMOUNT':
        # HouseKey يكون على شكل: 1-5 (للطابق الأول، الدار رقم 5)
        await record_payment_action(query, data[1], data[2])
        
    elif data[0] == 'STATS':
        if data[1] == 'UNPAID': await prompt_unpaid_floor(query)
        elif data[1] == 'LIST': 
            await show_house_list_by_amount(query, data[2], data[3])
        elif data[1] == 'RESET':
             await prompt_reset_confirmation(query, context)
        elif data[1] == 'CONFIRM': 
             await reset_action(query, context)
            
    elif data[0] == 'UNPAID': 
        await create_unpaid_file(query, data[1], context)

    elif data[0] == 'NO': 
        pass 

# ====================================================================
#              5. دوال عرض القوائم (تم التعديل لتصحيح أعداد الطابق الثاني)
# ====================================================================

async def show_branches(query: Update.callback_query, floor: str):
    """عرض قائمة الفروع مع أسماء محدثة حسب الطابق."""
    
    if floor == '1':
        # بيانات الطابق الأول الأصلية (10, 20, 20, 20, 15)
        branch_names = ["الفرع 1 (10 بيوت)", "الفرع 2 (20 بيتاً)", "الفرع 3 (20 بيتاً)", "الفرع 4 (20 بيتاً)", "الفرع 5 (15 بيتاً)"]
    elif floor == '2':
        # بيانات الطابق الثاني المحدثة (11, 22, 18, 11, 23)
        branch_names = ["الفرع 1 (11 بيتاً)", "الفرع 2 (22 بيتاً)", "الفرع 3 (18 بيتاً)", "الفرع 4 (11 بيتاً)", "الفرع 5 (23 بيتاً)"]
    else:
        branch_names = [] # في حالة وجود طابق غير معروف
        
    keyboard = []
    for i, name in enumerate(branch_names, 1):
        keyboard.append([InlineKeyboardButton(name, callback_data=f'BRANCH_{floor}_{str(i)}')])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='START')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"🏠 أنت الآن في الطابق **{floor}**.\n الرجاء اختيار الفرع:", reply_markup=reply_markup, parse_mode='Markdown')


async def show_branch_houses(query: Update.callback_query, floor: str, branch: str, chat_id: int, context): 
    
    # استخدام رقم الدار هنا بدلاً من المفتاح الفريد لكي يظل الترتيب صحيح
    houses = sorted([
        h for h in housing_data.values() 
        if str(h.get('floor')) == floor and str(h.get('branch_number')) == branch
    ], key=lambda x: x['house_number'])
    
    # محاولة حذف الرسالة السابقة لتنظيف الشاشة، مع تجاهل الأخطاء
    try:
        await query.delete_message()
    except Exception:
        pass 

    if not houses:
        await context.bot.send_message(chat_id, f"لا توجد بيانات بيوت في الطابق {floor} - فرع {branch} حالياً.")
        return

    # إرسال رسالة العنوان مرة واحدة
    await context.bot.send_message(chat_id, f"**قائمة بيوت الفرع {branch} في الطابق {floor}:**", parse_mode='Markdown')
    
    # إرسال كل بيت في رسالة مستقلة
    for house in houses:
        paid_amount = house['paid_amount']
        house_number = house['house_number']
        name = house['owner_name']
        
        # إنشاء مفتاح فريد للدار (Floor-HouseNumber) لاستخدامه في البايلود
        house_key = f"{floor}-{house_number}"
        
        status = "✅ مسدد بالكامل" if paid_amount >= MONTHLY_FEE else (
                 f"🟡 دفع {paid_amount:,}" if paid_amount > 0 else "❌ غير مسدد")
        button_text = f"تسجيل دفعة جديدة 💵"
        callback_data = f'PAY_{house_key}' # إرسال المفتاح الفريد
        
        keyboard = [[InlineKeyboardButton(button_text, callback_data=callback_data)]]
        
        message_text = (
            f"**دار رقم {house_number}**:\n"
            f"👤 {name}\n"
            f"💵 الحالة: {status}\n"
        )
        # استخدام مهلة زمنية عالية هنا أيضاً للمساعدة في إرسال الرسائل المتعددة
        await context.bot.send_message(chat_id, message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown', read_timeout=DEFAULT_TIMEOUT)

    back_keyboard = [[InlineKeyboardButton("🔙 رجوع للفروع", callback_data=f'MAIN_FLOOR_{floor}')]]
    await context.bot.send_message(chat_id, "انتهت القائمة.", reply_markup=InlineKeyboardMarkup(back_keyboard), read_timeout=DEFAULT_TIMEOUT)

# ====================================================================
#              6. دوال التسديد 
# ====================================================================

async def prompt_payment_amount(query: Update.callback_query, house_key: str):
    """يطلب من المستخدم اختيار مبلغ التسديد."""
    
    house = housing_data.get(house_key) # البحث باستخدام المفتاح الفريد
    
    if not house:
        await query.edit_message_text(f"❌ خطأ: لم يتم العثور على الدار.")
        return
        
    name = house['owner_name']
    paid_amount = house['paid_amount']
    house_number = house['house_number']
    
    keyboard = []
    for amount in PAYMENT_AMOUNTS:
        callback = f'AMOUNT_{house_key}_{amount}' # إرسال المفتاح الفريد
        keyboard.append(InlineKeyboardButton(f"💵 {amount:,} د.ع", callback_data=callback))
    
    row1 = keyboard[:3]
    row2 = keyboard[3:]
    
    keyboard_final = [row1, row2, [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='START')]]
    
    msg = (
        f"**تسجيل دفعة للدار رقم {house_number} ({name})**\n"
        f"المبلغ المسدد مسبقاً: **{paid_amount:,}** د.ع\n"
        f"الرجاء اختيار المبلغ المراد إضافته الآن:"
    )
    
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard_final), parse_mode='Markdown')

async def record_payment_action(query: Update.callback_query, house_key: str, amount_str: str):
    """يسجل المبلغ المدفوع ويحفظ البيانات في JSON."""
    
    try:
        amount_to_add = int(amount_str)
    except ValueError:
        await query.edit_message_text("❌ خطأ في القيمة المدخلة.", parse_mode=None)
        return

    house = housing_data.get(house_key) # البحث باستخدام المفتاح الفريد
    if not house:
        await query.edit_message_text(f"❌ خطأ: لم يتم العثور على الدار.")
        return

    house['paid_amount'] += amount_to_add
    name = house['owner_name']
    new_total = house['paid_amount']
    house_number = house['house_number']
    
    save_housing_data()
    
    status = "✅ مسدد بالكامل" if new_total >= MONTHLY_FEE else (
             f"🟡 دفع {new_total:,}" if new_total > 0 else "❌ غير مسدد")
             
    msg = (
        f"✅ **تم تسجيل دفعة!**\n\n"
        f"🏠 دار رقم: **{house_number}**\n"
        f"👤 الساكن: **{name}**\n"
        f"💵 المبلغ المضاف: **{amount_to_add:,}** د.ع\n"
        f"💰 الإجمالي المسدد: **{new_total:,}** د.ع\n"
        f"📌 الحالة: {status}"
    )
    
    back_keyboard = [[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='START')]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(back_keyboard), parse_mode='Markdown')

# ====================================================================
#              7. دالة البحث (تم التعديل للبحث الدقيق)
# ====================================================================
async def search_handler(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_authorized(user_id) or not update.message or not update.message.text: return
    search_term = update.message.text.strip()
    
    # إذا كان المستخدم في وضع الاسترجاع، يجب ألا يعمل البحث
    if context.user_data.get('awaiting_restore_file'):
        if search_term.lower() != '/cancel':
             await update.message.reply_text("⚠️ أنت الآن في وضع استعادة البيانات. يرجى إرسال ملف JSON أو إرسال الأمر `/cancel` للإلغاء.", parse_mode='Markdown')
        return

    results = []
    
    if search_term.isdigit():
        # البحث الدقيق برقم الدار فقط
        search_num = int(search_term)
        results = [
            (key, house) for key, house in housing_data.items()
            if house['house_number'] == search_num # مطابقة دقيقة لرقم الدار
        ]
        
    else:
        # البحث بالاسم (مطابقة جزئية غير حساسة لحالة الأحرف)
        lower_search_term = search_term.lower()
        results = [
            (key, house) for key, house in housing_data.items()
            if lower_search_term in house['owner_name'].lower()
        ]

    if results:
        # إذا كانت هناك نتائج متعددة (نفس رقم الدار في كلا الطابقين)، نعرض كل النتائج
        for house_key, house in results:
            house_number = house['house_number']
            name = house['owner_name']
            phone = house['phone_number']
            floor = house['floor']
            branch = house['branch_number']
            paid_amount = house['paid_amount']
            
            status = "✅ مسدد بالكامل" if paid_amount >= MONTHLY_FEE else (
                     f"🟡 دفع {paid_amount:,}" if paid_amount > 0 else "❌ غير مسدد")
                     
            info_text = (f"🔍 **نتيجة البحث عن: {search_term}**\n\n"
                         f"🏠 رقم الدار: **{house_number}**\n"
                         f"📍 الموقع: الطابق **{floor}** / الفرع **{branch}**\n"
                         f"👤 اسم صاحب الدار: **{name}**\n"
                         f"📞 رقم الهاتف: **{phone or 'غير متوفر'}**\n"
                         f"💵 الإجمالي المسدد: **{paid_amount:,}** د.ع\n"
                         f"📌 حالة التسديد: **{status}**\n")
                         
            keyboard = [[InlineKeyboardButton("💵 تسجيل دفعة جديدة", callback_data=f'PAY_{house_key}')]] # استخدام المفتاح الفريد
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(info_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ لم يتم العثور على دار برقم/اسم: **{search_term}**")

# ====================================================================
#              8. دوال الإحصائيات 
# ====================================================================

async def show_stats_menu(query: Update.callback_query) -> None:
    """عرض قائمة الإحصائيات مع الخيارات الجديدة."""
    
    total_houses = len(housing_data)
    total_collected = sum(h['paid_amount'] for h in housing_data.values())
    
    stats_text = (
        f"📊 **إحصائيات الرسوم الشهرية** 📊\n\n"
        f"عدد البيوت الكلي: **{total_houses}**\n"
        f"المبلغ الكلي الواصل: **{total_collected:,}** د.ع\n"
    )
    
    keyboard = []
    keyboard.append([InlineKeyboardButton("❌ جلب البيوت غير المسددة (ملف)", callback_data='STATS_UNPAID_FLOOR')])
    keyboard.append([InlineKeyboardButton("➖➖➖➖➖➖➖➖➖➖", callback_data='NO')])
    
    for amount in PAYMENT_AMOUNTS:
        callback_data = f'STATS_LIST_{amount}_All' 
        keyboard.append([InlineKeyboardButton(f"📄 جلب أسماء مسددي {amount:,} د.ع", callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("🔄 تصفير الأجور للشهر القادم", callback_data='STATS_RESET')])
    # تم إبقاء زر /restore هنا للتذكير، لكن الأمر يطلق يدوياً.
    keyboard.append([InlineKeyboardButton("📥 استرجاع نسخة احتياطية (أمر /restore)", callback_data='NO')]) 
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='START')])
    
    await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def prompt_unpaid_floor(query: Update.callback_query):
    """يطلب من المستخدم تحديد الطابق لعرض البيوت غير المسددة."""
    
    keyboard = [
        [InlineKeyboardButton("🏠 الطابق الأول (1)", callback_data='UNPAID_1')],
        [InlineKeyboardButton("🏢 الطابق الثاني (2)", callback_data='UNPAID_2')],
        [InlineKeyboardButton("🔙 رجوع للإحصائيات", callback_data='MAIN_STATS')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("الرجاء تحديد الطابق لعرض البيوت غير المسددة كملف:", reply_markup=reply_markup)

async def show_house_list_by_amount(query: Update.callback_query, amount_str: str, floor: str):
    """جلب وعرض قائمة أسماء البيوت حسب المبلغ المسدد والطابق."""
    
    amount = int(amount_str)
    
    results = [
        h for h in housing_data.values() 
        if h['paid_amount'] == amount and (floor == 'All' or str(h.get('floor')) == floor)
    ]
    
    results.sort(key=lambda h: h['house_number'])
    
    floor_filter_text = f"الطابق {floor}" if floor != 'All' else "جميع الطوابق"
    title = f"📄 قائمة البيوت التي سددت مبلغ **{amount:,}** د.ع في {floor_filter_text}:"
    
    message_text = title + "\n\n"
    if results:
        names = "\n".join([f"**{h['house_number']}** (طابق {h['floor']}) - {h['owner_name']} ({h['paid_amount']:,} د.ع)" for h in results])
        message_text += names
    else:
        message_text += "لا توجد بيوت تطابق هذا المعيار حالياً."
        
    back_button = [[InlineKeyboardButton("🔙 رجوع للإحصائيات", callback_data='MAIN_STATS')]]
    
    await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(back_button), parse_mode='Markdown')

# ====================================================================
#              9. دوال تصفير الأجور وإنشاء الملفات 
# ====================================================================

async def prompt_reset_confirmation(query: Update.callback_query, context):
    """يطلب تأكيد التصفير بزر شفاف."""
    
    msg = (f"⚠️ **تأكيد تصفير الأجور** ⚠️\n\n"
           f"سيتم **تصفير حقل `paid_amount`** لجميع البيوت وإرسال نسخة احتياطية قبل البدء.\n"
           f"هل أنت متأكد من المتابعة؟")
           
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد التصفير وإرسال نسخة احتياطية", callback_data='STATS_CONFIRM')],
        [InlineKeyboardButton("🔙 إلغاء والرجوع", callback_data='MAIN_STATS')]
    ]

    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def create_backup_action(chat_id: int, context) -> str:
    """إنشاء ملف نسخة احتياطية وإرساله."""
    # حفظ البيانات للتأكد من أن النسخة الاحتياطية محدثة
    save_housing_data() 
    
    try:
        with open(HOUSING_DATA_FILE, 'r', encoding='utf-8') as f:
            file_content = f.read()
    except FileNotFoundError:
        return "❌ فشل في قراءة ملف البيانات."

    backup_filename = f"Backup_Housing_Data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    try:
        # استخدام مهلة عالية هنا لضمان عدم حدوث TimedOut أثناء رفع الملف
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(file_content.encode('utf-8')),
            filename=backup_filename,
            caption="⚠️ **نسخة احتياطية للبيانات** قبل التصفير.",
            parse_mode='Markdown',
            read_timeout=DEFAULT_TIMEOUT # تطبيق المهلة
        )
        return "✅ تم إرسال نسخة احتياطية بنجاح."
    except TimedOut:
        return "❌ فشل في إرسال النسخة الاحتياطية (انتهت المهلة). سيتم التصفير الآن."
    except Exception as e:
        return f"❌ فشل في إرسال النسخة الاحتياطية (خطأ: {e}). سيتم التصفير الآن."

async def reset_action(query: Update.callback_query, context):
    """تنفيذ عملية النسخ الاحتياطي والتصفير الفعلية."""
    global housing_data
    chat_id = query.message.chat_id
    
    # 1. إشعار المستخدم بأن العملية بدأت
    await query.edit_message_text("جاري إرسال النسخة الاحتياطية قبل التصفير...", parse_mode='Markdown')
    
    # 2. إرسال النسخة الاحتياطية
    backup_status_msg = await create_backup_action(chat_id, context)
    
    # 3. تصفير البيانات
    for house in housing_data.values():
        house['paid_amount'] = 0
        
    save_housing_data()
    
    # 4. إرسال رسالة النجاح النهائية
    msg = (f"{backup_status_msg}\n\n"
           f"✅ **تمت عملية تصفير الأجور بنجاح!**\n\n"
           f"جميع حقول التسديد (`paid_amount`) أصبحت الآن 0 استعداداً للشهر الجديد.")
           
    back_button = [[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='START')]]
    
    # يتم استخدام context.bot.send_message بدلاً من query.edit_message_text بعد إرسال ملف
    await context.bot.send_message(chat_id, msg, reply_markup=InlineKeyboardMarkup(back_button), parse_mode='Markdown')


async def create_unpaid_file(query: Update.callback_query, floor: str, context):
    """جلب قائمة البيوت غير المسددة من الذاكرة وتحويلها لملف TXT."""
    
    if floor == '1':
        floor_filter_text = "الطابق الأول"
        file_name = "غير_المسددين_الطابق_الأول.txt"
    elif floor == '2':
        floor_filter_text = "الطابق الثاني"
        file_name = "غير_المسددين_الطابق_الثاني.txt"
    else:
        await query.edit_message_text("❌ خطأ في تحديد الطابق.")
        return

    results = [
        h for h in housing_data.values() 
        if str(h.get('floor')) == floor and h['paid_amount'] < MONTHLY_FEE
    ]
    
    results.sort(key=lambda h: h['house_number'])
    
    if not results:
        await query.edit_message_text(f"✅ لا توجد بيوت غير مسددة في **{floor_filter_text}**.", parse_mode='Markdown')
        return
        
    header = f"قائمة البيوت غير المسددة في {floor_filter_text} (دفع أقل من {MONTHLY_FEE:,} د.ع)\n"
    header += "---------------------------------------------------------\n"
    header += "الدار | الساكن | الهاتف | الطابق/الفرع | المبلغ المسدد\n"
    header += "---------------------------------------------------------\n"

    file_content = header
    for house in results:
        line = (
            f"{house['house_number']:<4} | "
            f"{house['owner_name']:<20} | "
            f"{house['phone_number'] or 'غير متوفر':<15} | "
            f"{house['floor']}/{house['branch_number']} | "
            f"{house['paid_amount']:,} د.ع\n"
        )
        file_content += line

    try:
        # استخدام مهلة عالية هنا لضمان عدم حدوث TimedOut أثناء رفع الملف
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(file_content.encode('utf-8')),
            filename=file_name,
            caption=f"❌ قائمة البيوت غير المسددة في **{floor_filter_text}**.",
            reply_to_message_id=query.message.message_id,
            read_timeout=DEFAULT_TIMEOUT # تطبيق المهلة
        )
        await query.edit_message_text(f"✅ تم إرسال قائمة البيوت غير المسددة في **{floor_filter_text}** كملف `{file_name}`.", parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء إرسال الملف: {e}")
        
# ====================================================================
#              10. دوال الاسترجاع (Restore) والإلغاء
# ====================================================================

async def restore_command(update: Update, context) -> None:
    """بدء وضع استعادة البيانات عند إرسال أمر /restore."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ لا تملك صلاحية.")
        return
        
    context.user_data['awaiting_restore_file'] = True
    await update.message.reply_text("⚠️ **وضع استعادة البيانات**\n\nالرجاء إرسال **ملف النسخة الاحتياطية (JSON)** الذي تريد استرجاعه الآن.\nلإلغاء العملية، أرسل الأمر: `/cancel`.", parse_mode='Markdown')

async def cancel_command(update: Update, context) -> None:
    """إلغاء عملية استعادة البيانات."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ لا تملك صلاحية.")
        return
        
    is_restoring = context.user_data.pop('awaiting_restore_file', False)
    
    if is_restoring:
        await update.message.reply_text("✅ تم إلغاء عملية استعادة البيانات.")
    else:
        await update.message.reply_text("لا توجد عملية قيد الانتظار لإلغائها.")

async def file_handler(update: Update, context) -> None:
    """معالجة الملفات المرسلة، خاصة ملفات JSON للاسترجاع."""
    user_id = update.effective_user.id
    if not is_authorized(user_id): return
    
    is_restoring = context.user_data.get('awaiting_restore_file')
    
    # نتحقق من الملف هنا لأن المرشح أصبح عاماً (filters.ATTACHMENT)
    if is_restoring and update.message.document: 
        del context.user_data['awaiting_restore_file']
        
        document = update.message.document
        if not document.file_name.lower().endswith('.json'):
            await update.message.reply_text("❌ فشل الاسترجاع: يجب أن يكون الملف بتنسيق JSON (ينتهي بـ .json).")
            return

        try:
            # تنزيل محتوى الملف في الذاكرة باستخدام مهلة عالية
            new_file = await context.bot.get_file(document.file_id)
            file_data = io.BytesIO()
            await new_file.download_to_memory(file_data, read_timeout=DEFAULT_TIMEOUT) # تطبيق المهلة
            file_data.seek(0)
            
            # تحميل واستبدال البيانات
            new_housing_data = json.load(file_data)
            
            global housing_data
            if not isinstance(new_housing_data, dict):
                 await update.message.reply_text("❌ فشل الاسترجاع: محتوى ملف JSON ليس قاموساً (Dictionary) صحيحاً.")
                 return
                 
            housing_data = new_housing_data
            save_housing_data() 
            
            await update.message.reply_text(f"✅ **تم استرجاع البيانات بنجاح!**\n\nتم تحميل {len(housing_data)} سجل جديد من الملف `{document.file_name}`.", parse_mode='Markdown')
            
        except TimedOut as e:
            await update.message.reply_text(f"❌ فشل الاسترجاع: حدثت مهلة زمنية أثناء تنزيل الملف. يرجى المحاولة مرة أخرى أو التأكد من استقرار اتصالك بالإنترنت. (الخطأ: {e})")
        except Exception as e:
            print(f"Restore Error: {e}")
            await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الملف واسترجاع البيانات: {e}\n(تأكد من أن الملف هو نسخة احتياطية من هذا البوت وبصيغة JSON صالحة).")
        
        return
        
# ====================================================================
#                          11. تشغيل البوت 
# ====================================================================

def main():
    """تحميل البيانات وتشغيل البوت."""
    
    load_housing_data()
    
    # 🌟 تطبيق المهلة الزمنية لـ 90 ثانية لجميع الطلبات
    application = ApplicationBuilder().token(TOKEN).concurrent_updates(True)\
        .read_timeout(DEFAULT_TIMEOUT).write_timeout(DEFAULT_TIMEOUT)\
        .build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restore", restore_command))
    application.add_handler(CommandHandler("cancel", cancel_command)) 
    
    application.add_handler(CallbackQueryHandler(handle_query, pattern='^(MAIN|BRANCH|PAY|AMOUNT|STATS|UNPAID|NO|START)')) 
    
    application.add_handler(MessageHandler(filters.ATTACHMENT, file_handler))
    
    # معالج النصوص (للبحث فقط، مع استبعاد الأوامر)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_handler)) 

    # 🌟 تسجيل معالج الأخطاء العام للتعامل مع أخطاء الشبكة والمهلة الزمنية
    application.add_error_handler(error_handler)

    print("بوت جرد الرسوم قيد التشغيل...")
    # تمرير المهلة الزمنية لـ run_polling أيضاً لضمان استمرار الاستماع
    application.run_polling(timeout=DEFAULT_TIMEOUT)

if __name__ == '__main__':
    main()
