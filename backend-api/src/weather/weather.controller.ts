import { Controller, Post, Body, UsePipes } from '@nestjs/common';
import { WeatherService } from './weather.service';
import {
  type CreateWeatherDto,
  createWeatherSchema,
} from './dto/create-weather.dto';
import { ZodValidationPipe } from './pipe/zod-validation.pipe';

@Controller('weather')
export class WeatherController {
  constructor(private readonly weatherService: WeatherService) {}

  @Post('create')
  @UsePipes(new ZodValidationPipe(createWeatherSchema))
  create(@Body() createWeatherDto: CreateWeatherDto) {
    return this.weatherService.create(createWeatherDto);
  }
}
