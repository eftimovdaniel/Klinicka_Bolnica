-- Постоечка база: додади табела за оцени по термин (изврши еднаш во MySQL Workbench или mysql клиент).
-- Зависи од Termin_pregled.

CREATE TABLE IF NOT EXISTS Pregled_feedback (
  feedback_ID INT NOT NULL AUTO_INCREMENT,
  termin_ID INT NOT NULL,
  ocena TINYINT NOT NULL,
  komentar TEXT,
  datum_na_ocena DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (feedback_ID),
  UNIQUE KEY uq_pf_termin (termin_ID),
  CONSTRAINT fk_pf_termin FOREIGN KEY (termin_ID) REFERENCES Termin_pregled (termin_ID)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT chk_pf_ocena CHECK (ocena >= 1 AND ocena <= 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
