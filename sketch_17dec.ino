#include <Keypad.h>
#include <Wire.h> 
#include <LiquidCrystal_I2C.h>
#include <Servo.h>
#include <DHT.h> 
#include <SPI.h> 
#include <MFRC522.h> 

int flameSensorPin = A15;
int ldrSensorPin = A1;
int ldrLedPin = 12;        
int vibrationSensorPin = 47;
int gasSensorPin = A0;
int buzzerPin = 11;
int ultrasonicSensorEchoPin = A2;
int ultrasonicSensorTrigPin = A3;
int waterSensorPin = A4;


int keypadServoPin = 10;
Servo keypadServo;
int cardServoPin = 13;
Servo cardServo;

// RFID
#define SS_PIN 53
#define RST_PIN 48
MFRC522 rfid(SS_PIN, RST_PIN);
String knownUID = "599276b2";

// LCD
LiquidCrystal_I2C lcd_1(0x27, 16, 2);  

// Keypad
const byte ROWS = 4;
const byte COLS = 4; 
char keys[ROWS][COLS] = {
  {'1','2','3','A'}, {'4','5','6','B'}, {'7','8','9','C'}, {'*','0','#','D'}
};
byte rowPins[4] = {9, 8, 7, 6};
byte colPins[COLS] = {5, 4, 3, 2};
Keypad keypad = Keypad(makeKeymap(keys), rowPins, colPins, ROWS, COLS);

char correctPassword[] = "1234A";
String enteredPassword = "";

unsigned long lastSensorLog = 0;
unsigned long logInterval = 1000; 

String currentAlarmState = "NORMAL"; 
unsigned long previousBuzzerMillis = 0;
bool buzzerState = false;   
int buzzerInterval = 0;     

float currentDistance = 0;

void setup()
{
    Serial.begin(9600);  
    Serial1.begin(9600); // Bluetooth (HC-05)
    
    pinMode(buzzerPin, OUTPUT);
    pinMode(ldrLedPin, OUTPUT);
    pinMode(ultrasonicSensorTrigPin, OUTPUT);
    pinMode(ultrasonicSensorEchoPin, INPUT);
    pinMode(vibrationSensorPin, INPUT);
    pinMode(flameSensorPin, INPUT);

    keypadServo.attach(keypadServoPin); keypadServo.write(0);
    cardServo.attach(cardServoPin); cardServo.write(0);
  
    lcd_1.init(); lcd_1.setBacklight(1);
    promptPassword();

    SPI.begin(); rfid.PCD_Init();
    Serial.println(F("System ready."));
}

void loop()
{
  checkIncomingCommand(); 
  
  manageAlarm();          

  manageLocalSensors();

  if (checkCard()) {   
    digitalWrite(buzzerPin, HIGH); delay(100); digitalWrite(buzzerPin, LOW);  
    cardServoMove();     
  }

  if (millis() - lastSensorLog >= logInterval) {
    logSensors();
    lastSensorLog = millis();
  }

  // 6. KEYPAD 
  char key = keypad.getKey();
  if (key) { 
    if (key == '#') checkPassword();
    else if (key == '*') resetPassword();
    else { enteredPassword += key; lcd_1.print('*'); }
  }
}


void manageLocalSensors() {
  
  if(analogRead(waterSensorPin) > 100) {
      digitalWrite(buzzerPin, HIGH); 
      lcd_1.setCursor(0,0);
      lcd_1.print("!!! FLOOD ALARM !!!");
      delay(1000);
      promptPassword();
      return; 
  }

  
  int ldrValue = analogRead(ldrSensorPin);
  if (ldrValue > 800) { 
    digitalWrite(ldrLedPin, HIGH); 
  } else {
    digitalWrite(ldrLedPin, LOW);
  }

  
  digitalWrite(ultrasonicSensorTrigPin, LOW); delayMicroseconds(2);
  digitalWrite(ultrasonicSensorTrigPin, HIGH); delayMicroseconds(10);
  digitalWrite(ultrasonicSensorTrigPin, LOW);
  long duration = pulseIn(ultrasonicSensorEchoPin, HIGH);
  currentDistance = duration * 0.034 / 2;
}


void checkIncomingCommand() {
  if (Serial1.available() > 0) {
    String command = Serial1.readStringUntil('\n');
    command.trim(); 
    if (command.startsWith("ALARM:")) {
      String newType = command.substring(6); 
      if (newType != currentAlarmState) {
        currentAlarmState = newType;
        
        
        lcd_1.clear(); 
        lcd_1.setCursor(0,0); 
        lcd_1.print("ALARM: " + newType);
        
        delay(1000); 
        promptPassword(); 
      }
    }
  }
}

void manageAlarm() {
  if (analogRead(waterSensorPin) > 100) return;

  if (currentAlarmState == "NORMAL") {
    digitalWrite(buzzerPin, LOW); buzzerState = false; return;
  }

  if (currentAlarmState == "FIRE" || currentAlarmState == "GAS") buzzerInterval = 100; 
  else if (currentAlarmState == "INTRUSION") buzzerInterval = 300; 
  else buzzerInterval = 500; 

  unsigned long currentMillis = millis();
  if (currentMillis - previousBuzzerMillis >= buzzerInterval) {
    previousBuzzerMillis = currentMillis;
    buzzerState = !buzzerState;
    digitalWrite(buzzerPin, buzzerState ? HIGH : LOW);
  }
}


void logSensors() {
  int gas = analogRead(gasSensorPin);
  int flame = analogRead(flameSensorPin);
  int ldr = analogRead(ldrSensorPin);
  int water = analogRead(waterSensorPin);
  int vib = digitalRead(vibrationSensorPin);

  String data = "GAS=" + String(gas) + ",FLAME=" + String(flame) + 
                ",LDR=" + String(ldr) + ",WATER=" + String(water) + 
                ",VIBRATION=" + String(vib) + ",DIST=" + String(currentDistance);

  Serial1.println("LOG;SENSORS;ALL;" + data);
}


void checkPassword() {
  lcd_1.clear();
  if (enteredPassword.equals(correctPassword)) {
    digitalWrite(buzzerPin,HIGH); delay(100); digitalWrite(buzzerPin,LOW);
    logEvent("KEYPAD","SUCCESS","PASS_OK");
    lcd_1.print("Door Opening...");
    openDoor(); delay(2000); closeDoor();
    resetPassword(); 
  } else {
    logEvent("KEYPAD","FAIL","WRONG_PASS");
    lcd_1.print("Incorrect Password!");
    delay(2000);
    resetPassword(); 
  }
}

void promptPassword() {
  lcd_1.clear();
  lcd_1.setCursor(0, 0);
  lcd_1.print("Enter password:");
  lcd_1.setCursor(0, 1);
}

void resetPassword() {
  enteredPassword = ""; 
  promptPassword(); 
}

void openDoor() { keypadServo.write(90); }
void closeDoor() { keypadServo.write(0); }

bool checkCard() {
  if (!(rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial())) return false;
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0"; 
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toLowerCase();
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  if (uid == knownUID) {
    logEvent("RFID","SUCCESS","UID_OK");
    return true;
  } else {
    logEvent("RFID","FAIL","UNKNOWN:" + uid);
    return false;
  }
}

void cardServoMove() {
  cardServo.write(90); delay(2000); cardServo.write(0); delay(500);
}

void logEvent(String source, String status, String details) {
  Serial1.println("EVENT|" + source + "|" + status + "|" + details);
}