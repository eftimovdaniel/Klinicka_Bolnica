-- Историја на AI чат за најавени пациенти и лекари
-- Изврши еднаш на постоечка база (mysql / Workbench / Azure Portal).

CREATE TABLE IF NOT EXISTS Ai_chat_session (
  session_id INT NOT NULL AUTO_INCREMENT,
  pacient_id INT DEFAULT NULL,
  doctor_id INT DEFAULT NULL,
  naslov VARCHAR(255) DEFAULT NULL,
  kontekst_json MEDIUMTEXT DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (session_id),
  KEY idx_ai_chat_pacient (pacient_id, updated_at),
  KEY idx_ai_chat_doctor (doctor_id, updated_at),
  CONSTRAINT fk_ai_chat_pacient FOREIGN KEY (pacient_id) REFERENCES patient (patient_ID)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_ai_chat_doctor FOREIGN KEY (doctor_id) REFERENCES Doctors (doctor_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Ai_chat_message (
  message_id INT NOT NULL AUTO_INCREMENT,
  session_id INT NOT NULL,
  uloga ENUM('user', 'assistant') NOT NULL,
  sodrzina TEXT NOT NULL,
  navigacija_json TEXT DEFAULT NULL,
  akcija VARCHAR(64) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (message_id),
  KEY idx_ai_chat_msg_session (session_id, created_at),
  CONSTRAINT fk_ai_chat_msg_session FOREIGN KEY (session_id) REFERENCES Ai_chat_session (session_id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
