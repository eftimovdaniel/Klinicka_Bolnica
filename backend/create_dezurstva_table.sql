-- Табела за дежурства (распоред на дежурства)
-- Оваа табела ќе се користи за чување на дежурствата наместо динамичко пресметување

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
