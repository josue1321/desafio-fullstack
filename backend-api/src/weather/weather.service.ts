import { Injectable } from '@nestjs/common';
import { CreateWeatherDto } from './dto/create-weather.dto';

@Injectable()
export class WeatherService {
  create(createWeatherDto: CreateWeatherDto) {
    return 'New weather object created';
  }
}
