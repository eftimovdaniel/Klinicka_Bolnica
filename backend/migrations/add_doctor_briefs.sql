-- Постоечка база: додади табела за дневни брифови за лекари (изврши еднаш во MySQL Workbench).
-- Зависи од Doctors. Безбедно за повторно извршување (CREATE TABLE IF NOT EXISTS).
--
-- UNIQUE индекс по (doctor_ID, brief_date) обезбедува дека scheduler-от
-- не прави дупликати ако случајно се извршi двапати истиот ден.

CREATE TABLE IF NOT EXISTS Doctor_briefs (
  brief_ID INT NOT NULL AUTO_INCREMENT,
  doctor_ID INT NOT NULL,
  brief_date DATE NOT NULL,
  -- готов текст на пораката (генериран од AI/scheduler)
  message TEXT NOT NULL,
  -- 0 = непрочитан, 1 = прочитан
  read_status TINYINT(1) NOT NULL DEFAULT 0,
  -- кога е генериран
  kreiran_na DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- кога е прочитан (NULL ако се уште не е)
  procitan_na DATETIME DEFAULT NULL,
  PRIMARY KEY (brief_ID),
  UNIQUE KEY uq_brief_doctor_date (doctor_ID, brief_date),
  KEY idx_brief_doctor (doctor_ID),
  CONSTRAINT fk_brief_doctor FOREIGN KEY (doctor_ID) REFERENCES Doctors (doctor_ID)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
