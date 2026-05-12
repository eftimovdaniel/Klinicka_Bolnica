-- ============================================================================
-- Potsetnici - табела за потсетници за прегледи
-- За AI агент функција #19 "Постави потсетник"
-- ============================================================================

CREATE TABLE IF NOT EXISTS Potsetnici (
  potsetnik_ID INT NOT NULL AUTO_INCREMENT,
  termin_ID INT NOT NULL,
  pacient_email VARCHAR(255) NOT NULL,
  vreme_za_potsetuvanje DATETIME NOT NULL,
  poraka TEXT,
  ispraten TINYINT(1) NOT NULL DEFAULT 0,
  kreirano DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (potsetnik_ID),
  KEY idx_pot_vreme_ispraten (vreme_za_potsetuvanje, ispraten),
  KEY idx_pot_termin (termin_ID),
  CONSTRAINT fk_pot_termin FOREIGN KEY (termin_ID) REFERENCES Termin_pregled (termin_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
