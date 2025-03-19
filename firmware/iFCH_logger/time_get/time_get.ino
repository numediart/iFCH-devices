#include <SparkFun_RV8803.h> //Get the library here:http://librarymanager/All#SparkFun_RV-8803

RV8803 rtc;

void setup()
{
  Wire.begin();

  Serial.begin(115200);
  Serial.println("Read Time from RTC Example");

  if (rtc.begin() == false)
  {
    Serial.println("Something went wrong, check wiring");
    while(1);
  }
  Serial.println("RTC online!");
}

void loop()
{
  if (rtc.updateTime() == true) //Updates the time variables from RTC
  {
    String currentDate = rtc.stringDateUSA(); //Get the current date in mm/dd/yyyy format (we're weird)
    //String currentDate = rtc.stringDate(); //Get the current date in dd/mm/yyyy format
    String currentTime = rtc.stringTime(); //Get the time
    Serial.print(currentDate);
    Serial.print(" ");
    Serial.println(currentTime);
  }
  else
  {
    Serial.print("RTC read failed");
  }
  delay(1000);
}