-- =============================================================================
-- SQL наредби за поддршка на Blob URL за слики на новости
-- =============================================================================

-- 1. Провери ја тековната дефиниција на колоната slika_path
--    (изврши во MySQL Workbench или командена линија)
-- DESCRIBE Novosti;

-- 2. Прошири ја колоната slika_path за да прифаќа долги URL-и (Azure Blob)
--    Ако веќе е VARCHAR(255), прошири ја на 1000
ALTER TABLE Novosti MODIFY COLUMN slika_path VARCHAR(1000) NULL;

-- 3. Ажурирај постоечка новост со Blob URL
--    Замени X со ID на новоста, и 'https://...' со вистинскиот URL
-- Пример:
-- UPDATE Novosti SET slika_path = 'https://kbstipstorage.blob.core.windows.net/kbstiptcontaine/novost-1.jpg' WHERE id = 1;

-- 4. Ажурирај повеќе новости одеднаш (пример)
-- UPDATE Novosti SET slika_path = 'https://kbstipstorage.blob.core.windows.net/kbstiptcontaine/novost-2.jpg' WHERE id = 2;
-- UPDATE Novosti SET slika_path = 'https://kbstipstorage.blob.core.windows.net/kbstiptcontaine/novost-3.jpg' WHERE id = 3;

-- 5. Приказ на сите новости со нивните ID и тековни slika_path (за референца)
-- SELECT id, naslov, slika_path FROM Novosti;
