-- Додај видео URL и дополнителни слики во Novosti (изврши ако табелата веќе постои)
USE Klinicka_Bolnica_Stip;

-- Ако добиеш грешка "Duplicate column", колоните веќе постојат
ALTER TABLE Novosti ADD COLUMN video_url VARCHAR(500) DEFAULT NULL;
ALTER TABLE Novosti ADD COLUMN slike_extra TEXT DEFAULT NULL;
