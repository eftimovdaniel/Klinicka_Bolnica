#!/usr/bin/env python3
"""
Скрипта за извршување на SQL фајлови во MySQL базата на податоци.
Користи ги credentials од .env фајлот.
"""
import sys
import os
from database import get_connection

def run_sql_file(sql_file_path):
    """Извршува SQL фајл во базата на податоци"""
    if not os.path.exists(sql_file_path):
        print(f"Грешка: Фајлот {sql_file_path} не постои!")
        return False
    
    conn = None
    db_cursor = None
    try:
        # Вчитај го SQL фајлот
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Воспостави конекција со базата
        conn = get_connection()
        db_cursor = conn.cursor()
        
        # Подели го SQL содржината на поединечни наредби (разделени со ;)
        # Филтрирај празни линии и коментари
        statements = []
        current_statement = ""
        
        for line in sql_content.split('\n'):
            line = line.strip()
            # Игнорирај празни линии и коментари кои започнуваат со --
            if not line or line.startswith('--'):
                continue
            
            current_statement += line + " "
            
            # Ако линијата завршува со ;, тоа е целосна наредба
            if line.endswith(';'):
                statements.append(current_statement.strip())
                current_statement = ""
        
        # Изврши ги сите наредби
        for statement in statements:
            if statement:
                try:
                    db_cursor.execute(statement)
                    print(f"✓ Извршено: {statement[:50]}...")
                except Exception as e:
                    print(f"✗ Грешка при извршување: {statement[:50]}...")
                    print(f"  Детали: {str(e)}")
                    # Продолжи со следната наредба
        
        # Зачувај ги промените
        conn.commit()
        print("\n✓ SQL фајлот е успешно извршен!")
        return True
        
    except Exception as e:
        print(f"✗ Грешка: {str(e)}")
        if conn:
            conn.rollback()
        return False
    finally:
        if db_cursor is not None:
            db_cursor.close()
        if conn is not None and conn.is_connected():
            conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Употреба: python run_sql_file.py <path_to_sql_file>")
        print("Пример: python run_sql_file.py create_aparati.sql")
        sys.exit(1)
    
    sql_file = sys.argv[1]
    
    # Ако е релативна патека, додај го backend директориумот
    if not os.path.isabs(sql_file):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sql_file = os.path.join(script_dir, sql_file)
    
    success = run_sql_file(sql_file)
    sys.exit(0 if success else 1)
