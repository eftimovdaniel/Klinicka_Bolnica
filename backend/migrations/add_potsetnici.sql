-- Постоечка база: додади табела за потсетници по термин (изврши еднаш во MySQL Workbench или mysql клиент).
-- Зависи од Termin_pregled.
--
-- Овој SQL е безбеден за повторно извршување (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS Potsetnici (
  potsetnik_ID INT NOT NULL AUTO_INCREMENT,
  termin_ID INT NOT NULL,
  email_pacient VARCHAR(255) NOT NULL,
  telefon_pacient VARCHAR(32) DEFAULT NULL,
  -- момент на праќање на потсетникот (DATE + TIME од терминот минус offsetот)
  vreme_potsetuvanje DATETIME NOT NULL,
  -- кој канал ќе се користи: email, sms, viber, push
  kanal VARCHAR(20) NOT NULL DEFAULT 'email',
  -- 0 = ненаправен, 1 = пратен, 2 = неуспех
  status_potsetnik TINYINT(1) NOT NULL DEFAULT 0,
  -- кога е креиран записот (за лог)
  kreiran_na DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- кога реално е пратен (NULL ако се уште не е пратен)
  prateno_na DATETIME DEFAULT NULL,
  PRIMARY KEY (potsetnik_ID),
  KEY idx_potsetnik_vreme_status (vreme_potsetuvanje, status_potsetnik),
  KEY idx_potsetnik_termin (termin_ID),
  CONSTRAINT fk_potsetnik_termin FOREIGN KEY (termin_ID) REFERENCES Termin_pregled (termin_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
