-- Facebook постови чекаат одобрување од директор пред објава на сајтот.
-- Пушти: mysql -u root -p Klinicka_Bolnica_Stip < backend/migrations/add_fb_post_pending.sql

CREATE TABLE IF NOT EXISTS Fb_post_pending (
  id INT AUTO_INCREMENT PRIMARY KEY,
  fb_post_id VARCHAR(64) NOT NULL,
  naslov VARCHAR(500) NOT NULL,
  sodrzina MEDIUMTEXT NOT NULL,
  slika_url VARCHAR(1024) DEFAULT NULL,
  fb_permalink VARCHAR(1024) DEFAULT NULL,
  fb_created_at DATETIME DEFAULT NULL,
  status ENUM('pending', 'published', 'skipped') NOT NULL DEFAULT 'pending',
  novost_id INT DEFAULT NULL,
  synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at DATETIME DEFAULT NULL,
  UNIQUE KEY uq_fb_post_id (fb_post_id),
  KEY idx_fb_status (status, synced_at),
  CONSTRAINT fk_fb_novost FOREIGN KEY (novost_id) REFERENCES Novosti(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
