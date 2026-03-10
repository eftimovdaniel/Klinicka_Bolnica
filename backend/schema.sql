-- Креирање на базата (ако ја немаш, отвори MySQL Workbench и изврши го целото)
-- USE Klinicka_Bolnica_Stip;   -- или креирај ја прво: CREATE DATABASE IF NOT EXISTS Klinicka_Bolnica_Stip CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; USE Klinicka_Bolnica_Stip;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS Doctors (
  doctor_ID INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(255) NOT NULL,
  surname VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL,
  specialty VARCHAR(255) DEFAULT NULL,
  password VARCHAR(255) NOT NULL,
  must_change_password TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (doctor_ID),
  UNIQUE KEY email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS patient (
  patient_ID INT NOT NULL AUTO_INCREMENT,
  name_patient VARCHAR(255) NOT NULL,
  surname_patient VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL,
  phone_number VARCHAR(50) DEFAULT NULL,
  password VARCHAR(255) NOT NULL,
  PRIMARY KEY (patient_ID),
  UNIQUE KEY email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Oddeli (
  id INT NOT NULL AUTO_INCREMENT,
  ime_na_oddel VARCHAR(255) NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Termin_pregled (
  termin_ID INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  ime_pacient VARCHAR(255) DEFAULT NULL,
  specijalnost_termin VARCHAR(255) DEFAULT NULL,
  ime_lekar VARCHAR(255) DEFAULT NULL,
  datum_pregled DATE NOT NULL,
  vreme_pregled TIME NOT NULL,
  status_pregled VARCHAR(50) DEFAULT 'закажан',
  email_pacient VARCHAR(255) DEFAULT NULL,
  telefon_pacient VARCHAR(50) DEFAULT NULL,
  napomena TEXT DEFAULT NULL,
  dijagnoza TEXT DEFAULT NULL,
  terapija TEXT DEFAULT NULL,
  PRIMARY KEY (termin_ID),
  KEY doctor_ID (doctor_ID),
  KEY datum_pregled (datum_pregled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Dezurstva (
  dezurstvo_ID INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  datum DATE NOT NULL,
  oddel VARCHAR(255) NOT NULL,
  vreme_od TIME NOT NULL,
  vreme_do TIME NOT NULL,
  napomena TEXT DEFAULT NULL,
  PRIMARY KEY (dezurstvo_ID),
  KEY doctor_ID (doctor_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Vrabotuvanje (
  id_oglas INT NOT NULL AUTO_INCREMENT,
  pozicija VARCHAR(255) NOT NULL,
  oddel VARCHAR(255) NOT NULL,
  datum_na_objava DATETIME DEFAULT NULL,
  datum_na_prijavuvanje DATETIME DEFAULT NULL,
  status_oglas VARCHAR(50) DEFAULT NULL,
  PRIMARY KEY (id_oglas)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prijaveni_lekari (
  id INT NOT NULL AUTO_INCREMENT,
  id_oglas INT NOT NULL,
  pozicija VARCHAR(255) DEFAULT NULL,
  ime_lekar VARCHAR(255) DEFAULT NULL,
  prezime_lekar VARCHAR(255) DEFAULT NULL,
  broj_med_licenca VARCHAR(100) DEFAULT NULL,
  email VARCHAR(255) DEFAULT NULL,
  telefon VARCHAR(50) DEFAULT NULL,
  datum_prijava DATETIME DEFAULT NULL,
  PRIMARY KEY (id),
  KEY id_oglas (id_oglas)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Aparati (
  aparat_id INT NOT NULL AUTO_INCREMENT,
  ime VARCHAR(255) NOT NULL,
  opis TEXT DEFAULT NULL,
  kod VARCHAR(50) DEFAULT NULL,
  aktiven TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (aparat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Aparati_termini (
  id INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  lekar_ime VARCHAR(255) DEFAULT NULL,
  pacient_ime VARCHAR(255) DEFAULT NULL,
  aparat VARCHAR(255) NOT NULL,
  datum_pregled DATE NOT NULL,
  vreme_pregled TIME NOT NULL,
  opis TEXT DEFAULT NULL,
  status VARCHAR(50) DEFAULT NULL,
  PRIMARY KEY (id),
  KEY doctor_ID (doctor_ID),
  KEY aparat (aparat)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Novosti (
  id INT NOT NULL AUTO_INCREMENT,
  naslov VARCHAR(500) NOT NULL,
  sodrzina TEXT NOT NULL,
  slika_path VARCHAR(500) DEFAULT NULL,
  slika_position VARCHAR(20) DEFAULT NULL,
  video_url VARCHAR(500) DEFAULT NULL,
  slike_extra TEXT DEFAULT NULL,
  author_doctor_id INT DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY author_doctor_id (author_doctor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id INT NOT NULL AUTO_INCREMENT,
  email VARCHAR(255) NOT NULL,
  token VARCHAR(64) NOT NULL,
  user_type ENUM('lekar','pacient') NOT NULL,
  expires_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY token (token),
  KEY email_type (email, user_type),
  KEY expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;

-- Пример податоци: еден оддел и еден лекар (лозинка: Test123..)
-- Лозинката е bcrypt хеш за "Test123.." – можеш да се најавиш со корисничко име: доктор.пример
INSERT IGNORE INTO Oddeli (ime_na_oddel) VALUES ('Општа медицина'), ('Кардиологија'), ('Педијатрија');

INSERT INTO Doctors (name, surname, email, specialty, password, must_change_password) VALUES
('Доктор', 'Пример', 'doktor.primer@bolnica.com', 'Општа медицина',
 '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
 0);
-- Корисничко име за најава: доктор.пример   Лозинка: Test123..
