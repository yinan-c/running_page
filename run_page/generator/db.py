import datetime
import random
import time
import string

from geopy.geocoders import options, Nominatim
from sqlalchemy import (
    Column,
    Float,
    Integer,
    Interval,
    String,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


# random user name 8 letters
def randomword():
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(4))


options.default_user_agent = "running_page"
# reverse the location (lat, lon) -> location detail
g = Nominatim(user_agent=randomword())

# Nominatim returns whatever the OSM name tags hold. Asking for Chinese yields
# values like "英国;英國" because OSM stores both scripts in one name:zh tag,
# so geocode in English and keep only the components the site actually shows.
GEOCODE_LANGUAGE = "en"
# Nominatim nests the populated place under different keys by country.
_CITY_KEYS = ("city", "town", "village", "municipality", "county", "suburb")
# At its default zoom Nominatim answers with the smallest administrative unit
# containing the point, which in some countries is a district rather than the
# city: Baohe District instead of Hefei. Zoom 6 resolves the city-level unit,
# but returns nothing for smaller cities such as Oxford, so query both and let
# the coarse answer win only when it actually names a city.
CITY_ZOOM = 6
_COARSE_CITY_KEYS = ("city", "town", "municipality")
# Nominatim asks for at most one request per second.
_GEOCODE_DELAY_SECONDS = 1.1


def _pick(address, keys):
    return next((address[k] for k in keys if address.get(k)), "")


def reverse_geocode(lat, lon):
    """Return "City, State, Country" for a coordinate, skipping empty parts."""
    detailed = g.reverse(f"{lat}, {lon}", language=GEOCODE_LANGUAGE)
    if detailed is None:
        return ""
    address = (detailed.raw or {}).get("address", {})
    city = _pick(address, _CITY_KEYS)

    time.sleep(_GEOCODE_DELAY_SECONDS)
    coarse = g.reverse(f"{lat}, {lon}", language=GEOCODE_LANGUAGE, zoom=CITY_ZOOM)
    if coarse is not None:
        city = _pick((coarse.raw or {}).get("address", {}), _COARSE_CITY_KEYS) or city

    # OSM names the London and Manchester conurbations "Greater ..."; the plain
    # name is what people call the city.
    if city.startswith("Greater "):
        city = city[len("Greater ") :]

    country = address.get("country", "")
    # OSM spells some Chinese prefecture-cities "Hangzhou City" and others
    # "Hefei". Scope the trim to China: elsewhere "City" is part of the name
    # (New York City, Kansas City).
    if country == "China" and city.endswith(" City"):
        city = city[: -len(" City")]

    parts = [city, address.get("state", ""), country]
    return ", ".join(p for p in parts if p)


ACTIVITY_KEYS = [
    "run_id",
    "name",
    "distance",
    "moving_time",
    "elapsed_time",
    "type",
    "subtype",
    "start_date",
    "start_date_local",
    "location_country",
    "summary_polyline",
    "average_heartrate",
    "max_heartrate",
    "average_speed",
    "max_speed",
    "average_cadence",
    "calories",
    "device_name",
    "elevation_gain",
    "elev_high",
    "elev_low",
]


class Activity(Base):
    __tablename__ = "activities"

    run_id = Column(Integer, primary_key=True)
    name = Column(String)
    distance = Column(Float)
    moving_time = Column(Interval)
    elapsed_time = Column(Interval)
    type = Column(String)
    subtype = Column(String)
    start_date = Column(String)
    start_date_local = Column(String)
    location_country = Column(String)
    summary_polyline = Column(String)
    average_heartrate = Column(Float)
    # 新增字段
    max_heartrate = Column(Float)
    average_speed = Column(Float)
    max_speed = Column(Float)
    average_cadence = Column(Float)
    calories = Column(Float)
    device_name = Column(String)
    elevation_gain = Column(Float)
    elev_high = Column(Float)
    elev_low = Column(Float)
    streak = None

    def to_dict(self):
        out = {}
        for key in ACTIVITY_KEYS:
            attr = getattr(self, key)
            if isinstance(attr, (datetime.timedelta, datetime.datetime)):
                out[key] = str(attr)
            else:
                out[key] = attr

        if self.streak:
            out["streak"] = self.streak

        return out


class ActivityLap(Base):
    __tablename__ = "activity_laps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, index=True)  # 关联 activities.run_id
    lap_index = Column(Integer)
    distance = Column(Float)
    elapsed_time = Column(Integer)  # 秒
    moving_time = Column(Integer)  # 秒
    average_speed = Column(Float)
    average_heartrate = Column(Float)
    total_elevation_gain = Column(Float)
    start_date = Column(String)

    def to_dict(self):
        return {
            "lap_index": self.lap_index,
            "distance": self.distance,
            "elapsed_time": self.elapsed_time,
            "moving_time": self.moving_time,
            "average_speed": self.average_speed,
            "average_heartrate": self.average_heartrate,
            "total_elevation_gain": self.total_elevation_gain,
            "start_date": self.start_date,
        }


class ActivityStream(Base):
    __tablename__ = "activity_streams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(Integer, index=True)  # 关联 activities.run_id
    stream_type = Column(String)  # heartrate/velocity_smooth/altitude/distance/time
    data = Column(String)  # JSON 数组

    def to_dict(self):
        import json
        try:
            return json.loads(self.data) if self.data else []
        except json.JSONDecodeError:
            return []


def update_or_create_activity(session, run_activity):
    created = False
    try:
        activity = (
            session.query(Activity).filter_by(run_id=int(run_activity.id)).first()
        )

        current_elevation_gain = 0.0  # default value

        # https://github.com/stravalib/stravalib/blob/main/src/stravalib/strava_model.py#L639C1-L643C41
        if (
            hasattr(run_activity, "total_elevation_gain")
            and run_activity.total_elevation_gain is not None
        ):
            current_elevation_gain = float(run_activity.total_elevation_gain)
        elif (
            hasattr(run_activity, "elevation_gain")
            and run_activity.elevation_gain is not None
        ):
            current_elevation_gain = float(run_activity.elevation_gain)

        if not activity:
            start_point = run_activity.start_latlng
            location_country = getattr(run_activity, "location_country", "")
            # or China for #176 to fix
            if not location_country and start_point or location_country == "China":
                try:
                    location_country = reverse_geocode(start_point.lat, start_point.lon)  # type: ignore
                # limit (only for the first time)
                except Exception:
                    try:
                        location_country = reverse_geocode(start_point.lat, start_point.lon)  # type: ignore
                    except Exception:
                        pass

            activity = Activity(
                run_id=run_activity.id,
                name=run_activity.name,
                distance=run_activity.distance,
                moving_time=run_activity.moving_time,
                elapsed_time=run_activity.elapsed_time,
                type=run_activity.type,
                subtype=getattr(run_activity, 'subtype', None) or getattr(run_activity, 'type', ''),
                start_date=run_activity.start_date,
                start_date_local=run_activity.start_date_local,
                location_country=location_country,
                summary_polyline=(
                    run_activity.map and run_activity.map.summary_polyline or ""
                ),
                average_heartrate=_safe_float(run_activity.average_heartrate),
                max_heartrate=_safe_float(getattr(run_activity, 'max_heartrate', None)),
                average_speed=_safe_float(run_activity.average_speed) or 0.0,
                max_speed=_safe_float(getattr(run_activity, 'max_speed', None)),
                average_cadence=_safe_float(getattr(run_activity, 'average_cadence', None)),
                calories=_safe_float(getattr(run_activity, 'calories', None)),
                device_name=getattr(run_activity, 'device_name', None),
                elevation_gain=current_elevation_gain,
                elev_high=_safe_float(getattr(run_activity, 'elev_high', None)),
                elev_low=_safe_float(getattr(run_activity, 'elev_low', None)),
            )
            session.add(activity)
            created = True
        else:
            activity.name = run_activity.name
            activity.distance = float(run_activity.distance)
            activity.moving_time = run_activity.moving_time
            activity.elapsed_time = run_activity.elapsed_time
            activity.type = run_activity.type
            activity.subtype = getattr(run_activity, 'subtype', None) or getattr(run_activity, 'type', '')
            activity.summary_polyline = (
                run_activity.map and run_activity.map.summary_polyline or ""
            )
            activity.average_heartrate = _safe_float(run_activity.average_heartrate)
            activity.max_heartrate = _safe_float(getattr(run_activity, 'max_heartrate', None))
            activity.average_speed = _safe_float(run_activity.average_speed) or 0.0
            activity.max_speed = _safe_float(getattr(run_activity, 'max_speed', None))
            activity.average_cadence = _safe_float(getattr(run_activity, 'average_cadence', None))
            activity.calories = _safe_float(getattr(run_activity, 'calories', None))
            activity.device_name = getattr(run_activity, 'device_name', None)
            activity.elevation_gain = current_elevation_gain
            activity.elev_high = _safe_float(getattr(run_activity, 'elev_high', None))
            activity.elev_low = _safe_float(getattr(run_activity, 'elev_low', None))
    except Exception as e:
        print(f"something wrong with {run_activity.id}")
        print(str(e))

    return created


def _convert_timedelta_to_seconds(value):
    """将 timedelta 对象转换为秒数"""
    import datetime
    if value is None:
        return 0
    if isinstance(value, datetime.timedelta):
        return int(value.total_seconds())
    if isinstance(value, (int, float)):
        return int(value)
    # stravalib 可能返回带有 unit 属性的对象
    if hasattr(value, 'unit'):
        # 尝试获取数值部分
        try:
            return int(float(str(value).split()[0]))
        except:
            pass
    return 0


def _safe_float(value):
    """安全转换为 float，处理 None 和带有 unit 属性的对象"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # stravalib 可能返回带有 unit 属性的对象
    if hasattr(value, 'unit'):
        try:
            # 尝试获取数值部分
            val_str = str(value).split()[0]
            return float(val_str)
        except:
            pass
    try:
        return float(value)
    except:
        return None


def update_or_create_lap(session, activity_id, lap_data, lap_index):
    """创建或更新活动圈数据"""

    try:
        lap = session.query(ActivityLap).filter_by(
            activity_id=int(activity_id),
            lap_index=lap_index
        ).first()

        if not lap:
            lap = ActivityLap(
                activity_id=int(activity_id),
                lap_index=lap_index,
                distance=_safe_float(lap_data.distance) or 0.0,
                elapsed_time=_convert_timedelta_to_seconds(lap_data.elapsed_time) if hasattr(lap_data, 'elapsed_time') else 0,
                moving_time=_convert_timedelta_to_seconds(lap_data.moving_time) if hasattr(lap_data, 'moving_time') else 0,
                average_speed=_safe_float(lap_data.average_speed),
                average_heartrate=_safe_float(lap_data.average_heartrate),
                total_elevation_gain=_safe_float(lap_data.total_elevation_gain),
                start_date=str(lap_data.start_date) if hasattr(lap_data, 'start_date') and lap_data.start_date else None,
            )
            session.add(lap)
        else:
            lap.distance = _safe_float(lap_data.distance) or 0.0
            lap.elapsed_time = _convert_timedelta_to_seconds(lap_data.elapsed_time) if hasattr(lap_data, 'elapsed_time') else 0
            lap.moving_time = _convert_timedelta_to_seconds(lap_data.moving_time) if hasattr(lap_data, 'moving_time') else 0
            lap.average_speed = _safe_float(lap_data.average_speed)
            lap.average_heartrate = _safe_float(lap_data.average_heartrate)
            lap.total_elevation_gain = _safe_float(lap_data.total_elevation_gain)
            lap.start_date = str(lap_data.start_date) if hasattr(lap_data, 'start_date') and lap_data.start_date else None

    except Exception as e:
        print(f"something wrong with lap {activity_id}-{lap_index}: {str(e)}")

    return True


def update_or_create_stream(session, activity_id, stream_type, stream_data):
    """创建或更新活动数据流"""
    import json

    try:
        stream = session.query(ActivityStream).filter_by(
            activity_id=int(activity_id),
            stream_type=stream_type
        ).first()

        # 将数据序列化为 JSON
        data_json = json.dumps(stream_data) if stream_data else "[]"

        if not stream:
            stream = ActivityStream(
                activity_id=int(activity_id),
                stream_type=stream_type,
                data=data_json,
            )
            session.add(stream)
        else:
            stream.data = data_json

    except Exception as e:
        print(f"something wrong with stream {activity_id}-{stream_type}: {str(e)}")

    return True


def add_missing_columns(engine, model):
    inspector = inspect(engine)
    table_name = model.__tablename__
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    missing_columns = []

    for column in model.__table__.columns:
        if column.name not in columns:
            missing_columns.append(column)
    if missing_columns:
        with engine.connect() as conn:
            for column in missing_columns:
                column_type = str(column.type)
                conn.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column.name} {column_type}"
                    )
                )


def init_db(db_path):
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)  # 会创建所有表

    # check missing columns for Activity
    add_missing_columns(engine, Activity)
    # check missing columns for ActivityLap
    add_missing_columns(engine, ActivityLap)
    # check missing columns for ActivityStream
    add_missing_columns(engine, ActivityStream)

    sm = sessionmaker(bind=engine)
    session = sm()
    session.commit()
    return session
