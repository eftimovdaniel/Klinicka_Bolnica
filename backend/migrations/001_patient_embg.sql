-- Идемпотентно: може да се изврши повторно без грешка ако колоната или индексот веќе постојат.
USE Klinicka_Bolnica_Stip;

SET @s = (
  SELECT IF(
    (
      SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'patient'
        AND COLUMN_NAME = 'embg'
    ) = 0,
    'ALTER TABLE patient ADD COLUMN embg VARCHAR(13) DEFAULT NULL COMMENT ''13-цифрен матичен број'' AFTER surname_patient',
    'SELECT ''Колоната embg веќе постои — прескокнато.'' AS migration_note'
  )
);
PREPARE stmt FROM @s;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @s2 = (
  SELECT IF(
    (
      SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'patient'
        AND INDEX_NAME = 'uq_patient_embg'
    ) = 0,
    'ALTER TABLE patient ADD UNIQUE KEY uq_patient_embg (embg)',
    'SELECT ''Индексот uq_patient_embg веќе постои — прескокнато.'' AS migration_note'
  )
);
PREPARE stmt2 FROM @s2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;
