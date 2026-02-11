-- Скрипта за креирање/ажурирање на табелите за администрација

-- 1. Креирање на табелата Dezurstva (ако не постои)
CREATE TABLE IF NOT EXISTS Dezurstva (
    dezurstvo_ID INT AUTO_INCREMENT PRIMARY KEY,
    doctor_ID INT NOT NULL,
    datum DATE NOT NULL,
    oddel VARCHAR(255) NOT NULL,
    vreme_od TIME NOT NULL DEFAULT '08:00:00',
    vreme_do TIME NOT NULL DEFAULT '20:00:00',
    napomena TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (doctor_ID) REFERENCES Doctors(doctor_ID) ON DELETE CASCADE,
    INDEX idx_doctor_datum (doctor_ID, datum),
    INDEX idx_datum (datum),
    INDEX idx_oddel (oddel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Проверка и ажурирање на табелата Vrabotuvanje
-- Прво провери дали постои колоната datum_na_objava
SET @dbname = DATABASE();
SET @tablename = 'Vrabotuvanje';
SET @columnname = 'datum_na_objava';
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE
      (table_name = @tablename)
      AND (table_schema = @dbname)
      AND (column_name = @columnname)
  ) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' DATE')
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- Проверка за колоната datum_na_prijavuvanje
SET @columnname = 'datum_na_prijavuvanje';
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE
      (table_name = @tablename)
      AND (table_schema = @dbname)
      AND (column_name = @columnname)
  ) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' DATE')
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- Проверка за колоната status_oglas
SET @columnname = 'status_oglas';
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE
      (table_name = @tablename)
      AND (table_schema = @dbname)
      AND (column_name = @columnname)
  ) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' VARCHAR(50)')
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;
