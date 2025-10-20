import pandas as pd
import folium
import json
import geopandas as gpd
import osmnx as ox
from folium.plugins import HeatMap
from shapely.geometry import Polygon

def parse_geojson_buildings(file_path):
    """
    Парсит GeoJSON файл и возвращает список в порядке: [широта, долгота, этажи]
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)
    
    buildings_list = []
    
    for feature in geojson_data['features']:
        properties = feature.get('properties', {})
        geometry = feature.get('geometry', {})
        
        # Извлекаем координаты
        if geometry.get('type') == 'Point' and 'coordinates' in geometry:
            # GeoJSON: [longitude, latitude]
            longitude, latitude = geometry['coordinates']
        else:
            continue  # Пропускаем объекты без координат
        
        # Извлекаем количество этажей
        building_levels = properties.get('building:levels')
        if building_levels:
            try:
                # Преобразуем в число
                floors = int(building_levels)
            except (ValueError, TypeError):
                floors = 1  # Значение по умолчанию
        else:
            floors = 1  # Если этажность не указана
        
        # Добавляем в список в нужном порядке: широта, долгота, этажи
        buildings_list.append([latitude, longitude, floors * 10])  # Уменьшил множитель для большей чувствительности
    
    return buildings_list

def visualize_polygons(geometry):
    lats, lons = get_lat_lon(geometry)
    
    m = folium.Map(location=[sum(lats)/len(lats), sum(lons)/len(lons)], zoom_start=13, tiles='cartodbpositron')
    
    overlay = gpd.GeoSeries(geometry).to_json()
    folium.GeoJson(overlay, name='boundary').add_to(m)
    
    return m

def get_lat_lon(geometry):
    lon = geometry.apply(lambda x: x.x if x.type == 'Point' else x.centroid.x)
    lat = geometry.apply(lambda x: x.y if x.type == 'Point' else x.centroid.y)
    return lat, lon

def get_city_boundary(city_name):
    """
    Получает границы города из OSM
    """
    try:
        print(f"🔍 Ищем границы для: {city_name}")
        polygon_city = ox.geometries_from_place(city_name, {'boundary':'administrative'}).reset_index()
        
        # Пробуем разные варианты названий для Нижнего Новгорода
        polygon_filtered = polygon_city[
            (polygon_city['name'].str.contains('Нижний Новгород', na=False)) |
            (polygon_city['name'].str.contains('Nizhny Novgorod', na=False)) |
            (polygon_city['admin_level'] == '8') |
            (polygon_city['admin_level'] == '6')
        ]
        
        if len(polygon_filtered) > 0:
            print(f"✅ Найдено полигонов: {len(polygon_filtered)}")
            return polygon_filtered
        else:
            print("⚠️ Полигоны не найдены, создаем вручную")
            # Создаем полигон вручную для Нижнего Новгорода
            nizhny_novgorod_bounds = [
                [56.20, 43.80],  # юго-запад
                [56.20, 44.10],  # юго-восток  
                [56.40, 44.10],  # северо-восток
                [56.40, 43.80],  # северо-запад
                [56.20, 43.80]   # замыкаем полигон
            ]
            
            manual_polygon = gpd.GeoDataFrame({
                'name': ['Нижний Новгород (ручной)'],
                'geometry': [Polygon(nizhny_novgorod_bounds)]
            })
            return manual_polygon
            
    except Exception as e:
        print(f"❌ Ошибка при получении границ: {e}")
        return None

# Загружаем данные зданий из GeoJSON
buildings_data = parse_geojson_buildings('data/houses.geojson')

# Создаем DataFrame для расчета максимального значения
df_buildings = pd.DataFrame(buildings_data, columns=['lat', 'lon', 'weight'])
max_weight = df_buildings['weight'].max()

print(f"📊 Обработано зданий: {len(buildings_data)}")
print(f"📈 Максимальный вес: {max_weight}")

# Получаем границы Нижнего Новгорода
print("\n🗺️ Получаем границы города...")
city_boundary = get_city_boundary('Нижний Новгород, Россия')

# Инициализация карты (центр на Нижний Новгород)
hmap = folium.Map(location=[56.326, 44.005], zoom_start=11)

# Добавляем границы города на карту
if city_boundary is not None:
    city_boundary_layer = folium.FeatureGroup(name='Границы города')
    
    # Конвертируем геометрию в GeoJSON и добавляем на карту
    boundary_geojson = gpd.GeoSeries(city_boundary['geometry']).to_json()
    folium.GeoJson(
        boundary_geojson,
        name='Границы Нижнего Новгорода',
        style_function=lambda x: {
            'fillColor': 'lightblue',
            'color': 'blue',
            'weight': 2,
            'fillOpacity': 0.1
        }
    ).add_to(city_boundary_layer)
    
    hmap.add_child(city_boundary_layer)
    print("✅ Границы города добавлены на карту")

# Слой с плотностью застройки - БОЛЕЕ ЧУВСТВИТЕЛЬНАЯ ВЕРСИЯ
building_density = folium.FeatureGroup(name='Распределение МСБ и ИП')

hm = HeatMap(
    buildings_data,
    min_opacity=0.3,  # Увеличил минимальную прозрачность
    max_val=max_weight * 0.4,  # Понизил максимальное значение для большей контрастности
    radius=8,  # Уменьшил радиус для более четких границ
    blur=10,     # Уменьшил размытие для большей детализации
    max_zoom=18,  # Увеличил максимальный зум
    gradient={    # Более контрастный градиент
        0.1: 'blue',
        0.2: 'blue',
        0.3: 'lime', 
        0.4: 'lime',
        0.5: 'yellow',
        0.6: 'yellow',
        0.7: 'orange',
        0.8: 'orange',
        0.9: 'red',
        1.0: 'red'
    }
)

building_density.add_child(hm)

# Собственные филиалы (если файл существует)
try:
    branches = pd.read_csv('data/branches.csv', sep=';')  # Добавил sep=';'
    filial_markers = folium.FeatureGroup(name='Отделения АО «Альфа-Банк»')

    for i, row in branches.iterrows():
        folium.Marker(
            location=[row['lat'], row['lon']],  # Исправлено с 'lng' на 'lon'
            popup=row['name'],
            icon=folium.DivIcon(
            html='<div style="font-size: 14px; font-weight: bold; color: white; background-color: #EF3124; border: 2px solid white; border-radius: 50%; width: 22px; height: 22px; text-align: center; line-height: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.3); font-family: Arial, sans-serif;">А</div>',
            icon_size=(22, 22),
            icon_anchor=(11, 11)
        )
        ).add_to(filial_markers)
    
    hmap.add_child(filial_markers)
    print("✅ Филиалы добавлены на карту")
except FileNotFoundError:
    print("⚠️ Файл branches.csv не найден")
except Exception as e:
    print(f"❌ Ошибка при загрузке филиалов: {e}")

# Конкуренты (если файл существует)
try:
    competitor = pd.read_csv('data/competitors.csv', sep=';')  # Добавил sep=';'
    competitor_markers = folium.FeatureGroup(name='Банки-конкуренты')

    for index, row in competitor.iterrows():
        folium.Marker(
            location=[row['lat'], row['lon']],  # Исправлено с 'lng' на 'lon'
            popup=row['name'],
            icon=folium.Icon(color='blue')
        ).add_to(competitor_markers)
    
    hmap.add_child(competitor_markers)
    print("✅ Конкуренты добавлены на карту")
except FileNotFoundError:
    print("⚠️ Файл competitors.csv не найден")
except Exception as e:
    print(f"❌ Ошибка при загрузке конкурентов: {e}")

# Добавляем основной слой
hmap.add_child(building_density)

# Управление слоями
folium.LayerControl(collapsed=False).add_to(hmap)

# Сохраняем карту
hmap.save('index.html')
print("✅ Чувствительная карта сохранена как 'index.html'")

# Дополнительно: показываем границы города отдельно
if city_boundary is not None:
    print("\n🔍 Показываем границы города...")
    boundary_map = visualize_polygons(city_boundary['geometry'])
    boundary_map.save('city_boundary.html')
    print("✅ Карта границ сохранена как 'city_boundary.html'")

print("\n🎯 НАСТРОЙКИ ДЛЯ БОЛЬШЕЙ ЧУВСТВИТЕЛЬНОСТИ:")
print("   • Уменьшен радиус (8) - четкие границы")
print("   • Уменьшено размытие (10) - больше деталей")
print("   • Увеличена минимальная прозрачность (0.3)")
print("   • Понижено максимальное значение для контраста")
print("   • Более агрессивный градиент цветов")