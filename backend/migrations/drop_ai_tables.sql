-- Bришење на AI агент-табелите од постоечка база на податоци.
-- Изврши еднаш на Azure MySQL (преку mysql CLI или Workbench или Azure Portal).
--
-- Безбедно за повторно извршување (IF EXISTS).
-- ВАЖНО: Ова бришe ПОДАТОЦИ - сите потсетници, брифови и FAQ записи се губат.

-- Исклучи foreign-key проверки за да дозволиме бришење без редослед
SET FOREIGN_KEY_CHECKS = 0;

-- FAQ – често поставувани прашања (немало foreign keys кон неа)
DROP TABLE IF EXISTS FAQ;

-- Doctor_briefs – дневен брифинг за лекари
DROP TABLE IF EXISTS Doctor_briefs;

-- Potsetnici – потсетници за термини за пациенти
DROP TABLE IF EXISTS Potsetnici;

-- Вклучи ги назад foreign-key проверките
SET FOREIGN_KEY_CHECKS = 1;

-- Провери дали се сите тргнати (треба да врати 0 редови)
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('FAQ', 'Doctor_briefs', 'Potsetnici');
