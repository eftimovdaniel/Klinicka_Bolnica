-- Изврши го ова ако веќе имаш креирана база и сакаш само да ја додадеш табелата Novosti
USE Klinicka_Bolnica_Stip;

CREATE TABLE IF NOT EXISTS Novosti (
  id INT NOT NULL AUTO_INCREMENT,
  naslov VARCHAR(500) NOT NULL,
  sodrzina TEXT NOT NULL,
  slika_path VARCHAR(500) DEFAULT NULL,
  video_url VARCHAR(500) DEFAULT NULL,
  slike_extra TEXT DEFAULT NULL,
  author_doctor_id INT DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY author_doctor_id (author_doctor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
