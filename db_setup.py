import sqlite3
import os
from floor1_data import FLOOR_1_DATA
from floor2_data import FLOOR_2_DATA

# اسم ملف قاعدة البيانات (يجب أن يطابق ما في main.py)
DB_NAME = 'housing_complex.db'

# 1. دمج البيانات مع إعادة ترقيم الطابق الثاني
def merge_and_reindex_data():
    """يدمج بيانات الطابقين، مع إعادة ترقيم بيوت الطابق الثاني لتبدأ من 86."""
    print("بدء عملية دمج وإعادة ترقيم البيانات...")
    
    all_data = []
    
    # الطابق الأول (1-85)
    all_data.extend(FLOOR_1_DATA)
    
    # عدد بيوت الطابق الأول لتحديد نقطة بداية الطابق الثاني
    floor1_count = len(FLOOR_1_DATA)
    
    # الطابق الثاني (الترقيم يبدأ من 86 = 85 + (الرقم في ملف floor2_data.py))
    for house_number, owner_name, phone_number, floor, branch_number in FLOOR_2_DATA:
        # house_number هنا هو الرقم من 1 إلى 85 (كما عدلناه لك في الطلب السابق)
        new_house_number = house_number + floor1_count
        all_data.append((new_house_number, owner_name, phone_number, floor, branch_number))

    print(f"تم دمج {len(all_data)} سجل بنجاح.")
    return all_data

# 2. إنشاء قاعدة البيانات والجداول
def create_database(data):
    """ينشئ قاعدة البيانات الجدول ويملاه بالبيانات المدمجة."""
    
    # حذف الملف القديم لضمان الإنشاء من الصفر
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"تم حذف ملف قاعدة البيانات القديم: {DB_NAME}")
        
    conn = None
    try:
        # الاتصال بقاعدة البيانات (سيتم إنشاؤها إذا لم تكن موجودة)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # إنشاء جدول البيوت
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS houses (
                house_number INTEGER PRIMARY KEY,
                owner_name TEXT NOT NULL,
                phone_number TEXT,
                floor TEXT NOT NULL,
                branch_number INTEGER NOT NULL
            )
        """)
        
        # إنشاء جدول الدفعات
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                house_number INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                amount INTEGER NOT NULL,
                FOREIGN KEY (house_number) REFERENCES houses (house_number)
            )
        """)

        # 3. إدخال بيانات البيوت المدمجة في الجدول
        cursor.executemany("""
            INSERT INTO houses (house_number, owner_name, phone_number, floor, branch_number)
            VALUES (?, ?, ?, ?, ?)
        """, data)

        conn.commit()
        print(f"✅ تم إنشاء جدول 'houses' وإدخال {len(data)} سجل بنجاح في {DB_NAME}")

    except sqlite3.Error as e:
        print(f"❌ حدث خطأ في قاعدة البيانات: {e}")
        
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    merged_data = merge_and_reindex_data()
    if merged_data:
        create_database(merged_data)
        print("\nعملية إنشاء قاعدة البيانات اكتملت بنجاح.")

