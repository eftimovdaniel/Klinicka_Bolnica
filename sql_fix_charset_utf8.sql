-- Проверка и поправка на UTF-8 кодирање за кирилица
-- Изврши на VM: mysql -u root -p Klinicka_Bolnica_Stip < sql_fix_charset_utf8.sql

-- 1. Провери тековно кодирање на базата и табелите
-- SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'Klinicka_Bolnica_Stip';

-- 2. Промени базата на utf8mb4
ALTER DATABASE Klinicka_Bolnica_Stip CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- 3. Промени табелата Doctors (и други со текст)
ALTER TABLE Doctors CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE Oddeli CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE Vrabotuvanje CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE Novosti CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
