#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

int scanTime = 5;  // In seconds
BLEScan *pBLEScan;
BLEAdvertisedDevice *targetDevice = nullptr;
BLEClient *pClient = nullptr;
BLERemoteService *pRemoteService = nullptr;
BLERemoteCharacteristic *pRemoteCharacteristic = nullptr;

const char *targetDeviceName = "YourTargetDeviceName";  // Replace with your target device name
const char *targetServiceUUID = "YourTargetServiceUUID";  // Replace with your target service UUID
const char *targetCharacteristicUUID = "YourTargetCharacteristicUUID";  // Replace with your target characteristic UUID

class MyAdvertisedDeviceCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    Serial.printf("Advertised Device: %s \n", advertisedDevice.toString().c_str());
    if (advertisedDevice.getName() == targetDeviceName) {
      targetDevice = new BLEAdvertisedDevice(advertisedDevice);
      pBLEScan->stop();
    }
  }
};

bool connectToServer(BLEAdvertisedDevice *pAdvertisedDevice) {
  Serial.print("Forming a connection to ");
  Serial.println(pAdvertisedDevice->getAddress().toString().c_str());

  pClient = BLEDevice::createClient();
  Serial.println(" - Created client");

  // Connect to the remove BLE Server.
  pClient->connect(pAdvertisedDevice);
  Serial.println(" - Connected to server");

  // Obtain a reference to the service we are after in the remote BLE server.
  pRemoteService = pClient->getService(BLEUUID(targetServiceUUID));
  if (pRemoteService == nullptr) {
    Serial.print("Failed to find our service UUID: ");
    Serial.println(targetServiceUUID);
    pClient->disconnect();
    return false;
  }
  Serial.println(" - Found our service");

  // Obtain a reference to the characteristic in the service of the remote BLE server.
  pRemoteCharacteristic = pRemoteService->getCharacteristic(BLEUUID(targetCharacteristicUUID));
  if (pRemoteCharacteristic == nullptr) {
    Serial.print("Failed to find our characteristic UUID: ");
    Serial.println(targetCharacteristicUUID);
    pClient->disconnect();
    return false;
  }
  Serial.println(" - Found our characteristic");

  // Read the value of the characteristic.
  if (pRemoteCharacteristic->canRead()) {
    std::string value = pRemoteCharacteristic->readValue();
    Serial.print("The characteristic value was: ");
    Serial.println(value.c_str());
  }

  return true;
}

void setup() {
  Serial.begin(115200);
  Serial.println("Scanning...");

  BLEDevice::init("");
  pBLEScan = BLEDevice::getScan();  // create new scan
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setActiveScan(true);  // active scan uses more power, but get results faster
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);  // less or equal setInterval value
}

void loop() {
  if (targetDevice == nullptr) {
    BLEScanResults *foundDevices = pBLEScan->start(scanTime, false);
    Serial.print("Devices found: ");
    Serial.println(foundDevices->getCount());
    Serial.println("Scan done!");
    pBLEScan->clearResults();  // delete results from BLEScan buffer to release memory
    delay(2000);
  } else {
    if (connectToServer(targetDevice)) {
      Serial.println("Connected to the target device.");
      while (Serial.available() > 0) {
        String command = Serial.readStringUntil('\n');
        if (pRemoteCharacteristic->canWrite()) {
          pRemoteCharacteristic->writeValue(command.c_str(), command.length());
          Serial.print("Sent command: ");
          Serial.println(command);
        }
      }
    } else {
      Serial.println("Failed to connect to the target device.");
    }
    delay(2000);
  }
}