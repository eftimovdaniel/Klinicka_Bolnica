-- =============================================================================
-- Клиничка Болница Штип – само структура (празни табели), MySQL 8+
-- Користи: креирај празна база, пополнувај во Workbench, па Export.
-- Целосна верзија со примерни податоци: schema.sql
-- =============================================================================

CREATE DATABASE IF NOT EXISTS Klinicka_Bolnica_Stip
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE Klinicka_Bolnica_Stip;

SET NAMES utf8mb4;

-- Oddeli – одделенија (/uslugi)
CREATE TABLE Oddeli (
  id INT NOT NULL AUTO_INCREMENT,
  ime_na_oddel VARCHAR(255) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_oddel_ime (ime_na_oddel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Doctors – лекари
CREATE TABLE Doctors (
  doctor_ID INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(120) NOT NULL,
  surname VARCHAR(120) NOT NULL,
  specialty VARCHAR(120) DEFAULT NULL,
  email VARCHAR(255) NOT NULL,
  password VARCHAR(255) NOT NULL,
  must_change_password TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (doctor_ID),
  UNIQUE KEY uq_doctors_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- patient – пациенти
CREATE TABLE patient (
  patient_ID INT NOT NULL AUTO_INCREMENT,
  name_patient VARCHAR(120) NOT NULL,
  surname_patient VARCHAR(120) NOT NULL,
  email VARCHAR(255) NOT NULL,
  phone_number VARCHAR(32) DEFAULT NULL,
  password VARCHAR(255) NOT NULL,
  PRIMARY KEY (patient_ID),
  UNIQUE KEY uq_patient_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- password_reset_tokens – заборавена лозинка
CREATE TABLE password_reset_tokens (
  id INT NOT NULL AUTO_INCREMENT,
  email VARCHAR(255) NOT NULL,
  token VARCHAR(255) NOT NULL,
  user_type VARCHAR(20) NOT NULL,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  KEY idx_prt_token (token),
  KEY idx_prt_email_type (email, user_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Termin_pregled – закажани прегледи
CREATE TABLE Termin_pregled (
  termin_ID INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  ime_pacient VARCHAR(255) NOT NULL,
  specijalnost_termin VARCHAR(120) DEFAULT NULL,
  ime_lekar VARCHAR(255) DEFAULT NULL,
  datum_pregled DATE NOT NULL,
  vreme_pregled TIME NOT NULL,
  status_pregled VARCHAR(40) DEFAULT 'закажан',
  email_pacient VARCHAR(255) DEFAULT NULL,
  telefon_pacient VARCHAR(32) DEFAULT NULL,
  napomena TEXT,
  dijagnoza TEXT,
  terapija TEXT,
  PRIMARY KEY (termin_ID),
  KEY idx_tp_doctor_datum (doctor_ID, datum_pregled),
  KEY idx_tp_status (status_pregled),
  CONSTRAINT fk_tp_doctor FOREIGN KEY (doctor_ID) REFERENCES Doctors (doctor_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Pregled_feedback – оцена за завршен термин (една по termin_ID)
CREATE TABLE Pregled_feedback (
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

-- Novosti
CREATE TABLE Novosti (
  id INT NOT NULL AUTO_INCREMENT,
  naslov VARCHAR(500) NOT NULL,
  sodrzina MEDIUMTEXT NOT NULL,
  slika_path VARCHAR(1024) DEFAULT NULL,
  slika_position VARCHAR(64) DEFAULT NULL,
  slika_height VARCHAR(32) DEFAULT NULL,
  video_url VARCHAR(1024) DEFAULT NULL,
  slike_extra TEXT DEFAULT NULL,
  author_doctor_id INT DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_novosti_author (author_doctor_id),
  CONSTRAINT fk_novosti_doctor FOREIGN KEY (author_doctor_id) REFERENCES Doctors (doctor_ID)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dezurstva
CREATE TABLE Dezurstva (
  dezurstvo_ID INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  datum DATE NOT NULL,
  oddel VARCHAR(255) NOT NULL,
  vreme_od TIME NOT NULL,
  vreme_do TIME NOT NULL,
  napomena TEXT,
  PRIMARY KEY (dezurstvo_ID),
  KEY idx_dez_doctor_datum (doctor_ID, datum),
  CONSTRAINT fk_dez_doctor FOREIGN KEY (doctor_ID) REFERENCES Doctors (doctor_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Vrabotuvanje – огласи
CREATE TABLE Vrabotuvanje (
  id_oglas INT NOT NULL AUTO_INCREMENT,
  pozicija VARCHAR(255) NOT NULL,
  oddel VARCHAR(255) NOT NULL,
  datum_na_objava DATE NOT NULL,
  datum_na_prijavuvanje DATE NOT NULL,
  status_oglas VARCHAR(64) DEFAULT NULL,
  PRIMARY KEY (id_oglas)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- prijaveni_lekari
CREATE TABLE prijaveni_lekari (
  id INT NOT NULL AUTO_INCREMENT,
  id_oglas INT DEFAULT NULL,
  pozicija VARCHAR(255) NOT NULL,
  ime_lekar VARCHAR(120) NOT NULL,
  prezime_lekar VARCHAR(120) NOT NULL,
  broj_med_licenca BIGINT DEFAULT NULL,
  email VARCHAR(255) NOT NULL,
  telefon BIGINT DEFAULT NULL,
  datum_prijava DATETIME NOT NULL,
  PRIMARY KEY (id),
  KEY idx_pl_oglas (id_oglas),
  CONSTRAINT fk_pl_oglas FOREIGN KEY (id_oglas) REFERENCES Vrabotuvanje (id_oglas)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Aparati
CREATE TABLE Aparati (
  aparat_id INT NOT NULL AUTO_INCREMENT,
  ime VARCHAR(255) NOT NULL,
  opis TEXT,
  kod VARCHAR(64) NOT NULL,
  aktiven TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (aparat_id),
  UNIQUE KEY uq_aparat_kod (kod)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Aparati_termini
CREATE TABLE Aparati_termini (
  aparat_termin_id INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  lekar_ime VARCHAR(255) NOT NULL,
  pacient_ime VARCHAR(255) NOT NULL,
  aparat VARCHAR(64) NOT NULL,
  datum_pregled DATE NOT NULL,
  vreme_pregled TIME NOT NULL,
  opis TEXT NOT NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'закажан',
  PRIMARY KEY (aparat_termin_id),
  KEY idx_at_aparat_datum (aparat, datum_pregled, vreme_pregled),
  CONSTRAINT fk_at_doctor FOREIGN KEY (doctor_ID) REFERENCES Doctors (doctor_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
