"""Estados de México: nombres oficiales, capitales, alias y municipios grandes para deducir el estado.

Se usa para llenar LostReport.state cuando la app no lo manda (reportes por WhatsApp, importaciones)
y para normalizar lo que escribe la gente ("CDMX", "Edo. de México", "N.L.", "Torreón, Coahuila"...).
No pretende ser un catálogo completo de municipios: cubre capitales, zonas metropolitanas y las
ciudades donde más se reportan perritos. Lo que no está aquí queda sin estado (None).
"""
import math
import re
import unicodedata

# (nombre oficial corto, capital, latitud, longitud de la capital, alias y abreviaturas)
STATES: tuple[tuple[str, str, float, float, tuple[str, ...]], ...] = (
    ("Aguascalientes", "Aguascalientes", 21.8818, -102.2916, ("ags",)),
    ("Baja California", "Mexicali", 32.6245, -115.4523, ("bc", "baja california norte", "bcn")),
    ("Baja California Sur", "La Paz", 24.1426, -110.3128, ("bcs",)),
    ("Campeche", "San Francisco de Campeche", 19.8301, -90.5349, ("camp", "cam")),
    ("Chiapas", "Tuxtla Gutiérrez", 16.7516, -93.1161, ("chis", "chps")),
    ("Chihuahua", "Chihuahua", 28.6353, -106.0889, ("chih", "chh")),
    ("Ciudad de México", "Ciudad de México", 19.4326, -99.1332,
     ("cdmx", "df", "d.f.", "distrito federal", "mexico df", "mexico d.f.", "mexico city", "ciudad de mexico")),
    ("Coahuila", "Saltillo", 25.4232, -101.0053, ("coah", "coahuila de zaragoza")),
    ("Colima", "Colima", 19.2433, -103.7250, ("col",)),
    ("Durango", "Victoria de Durango", 24.0277, -104.6532, ("dgo", "dur")),
    ("Guanajuato", "Guanajuato", 21.0190, -101.2574, ("gto",)),
    ("Guerrero", "Chilpancingo de los Bravo", 17.5506, -99.5024, ("gro",)),
    ("Hidalgo", "Pachuca de Soto", 20.1011, -98.7591, ("hgo", "hid")),
    ("Jalisco", "Guadalajara", 20.6597, -103.3496, ("jal",)),
    ("México", "Toluca de Lerdo", 19.2826, -99.6557,
     ("edomex", "edo mex", "edo. mex.", "edo de mexico", "edo. de mexico", "estado de mexico", "mex")),
    ("Michoacán", "Morelia", 19.7008, -101.1844, ("mich", "michoacan de ocampo")),
    ("Morelos", "Cuernavaca", 18.9242, -99.2216, ("mor",)),
    ("Nayarit", "Tepic", 21.5041, -104.8946, ("nay",)),
    ("Nuevo León", "Monterrey", 25.6866, -100.3161, ("nl", "n.l.")),
    ("Oaxaca", "Oaxaca de Juárez", 17.0732, -96.7266, ("oax",)),
    ("Puebla", "Puebla de Zaragoza", 19.0414, -98.2063, ("pue",)),
    ("Querétaro", "Santiago de Querétaro", 20.5888, -100.3899, ("qro", "queretaro de arteaga")),
    ("Quintana Roo", "Chetumal", 18.5002, -88.2961, ("qroo", "q. roo", "q roo", "qr")),
    ("San Luis Potosí", "San Luis Potosí", 22.1565, -100.9855, ("slp", "s.l.p.")),
    ("Sinaloa", "Culiacán", 24.8091, -107.3940, ("sin",)),
    ("Sonora", "Hermosillo", 29.0729, -110.9559, ("son",)),
    ("Tabasco", "Villahermosa", 17.9892, -92.9281, ("tab",)),
    ("Tamaulipas", "Ciudad Victoria", 23.7369, -99.1411, ("tamps", "tam")),
    ("Tlaxcala", "Tlaxcala de Xicohténcatl", 19.3139, -98.2404, ("tlax",)),
    ("Veracruz", "Xalapa-Enríquez", 19.5438, -96.9102, ("ver", "veracruz de ignacio de la llave")),
    ("Yucatán", "Mérida", 20.9674, -89.5926, ("yuc",)),
    ("Zacatecas", "Zacatecas", 22.7709, -102.5833, ("zac",)),
)

STATE_NAMES: tuple[str, ...] = tuple(s[0] for s in STATES)

# Municipios y ciudades grandes -> estado (además de las capitales, que se agregan solas)
CITIES: dict[str, tuple[str, ...]] = {
    "Aguascalientes": ("jesus maria", "calvillo"),
    "Baja California": ("tijuana", "ensenada", "tecate", "rosarito", "playas de rosarito", "san felipe"),
    "Baja California Sur": ("los cabos", "cabo san lucas", "san jose del cabo", "loreto", "comondu"),
    "Campeche": ("ciudad del carmen", "campeche", "champoton", "escarcega"),
    "Chiapas": ("tuxtla", "tapachula", "san cristobal de las casas", "san cristobal", "comitan", "palenque"),
    "Chihuahua": ("ciudad juarez", "cd juarez", "cd. juarez", "juarez", "delicias", "cuauhtemoc", "parral",
                  "hidalgo del parral", "nuevo casas grandes"),
    "Ciudad de México": ("coyoacan", "iztapalapa", "gustavo a. madero", "gustavo a madero", "alvaro obregon",
                         "tlalpan", "xochimilco", "benito juarez", "cuauhtemoc cdmx", "miguel hidalgo",
                         "azcapotzalco", "iztacalco", "venustiano carranza", "tlahuac", "magdalena contreras",
                         "la magdalena contreras", "cuajimalpa", "milpa alta", "polanco", "roma norte", "condesa",
                         "santa fe", "del valle", "narvarte"),
    "Coahuila": ("saltillo", "torreon", "monclova", "piedras negras", "acuna", "ciudad acuna", "ramos arizpe",
                 "san pedro", "matamoros coahuila", "frontera", "sabinas"),
    "Colima": ("manzanillo", "tecoman", "villa de alvarez"),
    "Durango": ("durango", "gomez palacio", "lerdo", "ciudad lerdo"),
    "Guanajuato": ("leon", "irapuato", "celaya", "salamanca", "silao", "san miguel de allende", "dolores hidalgo",
                   "guanajuato", "acambaro", "valle de santiago", "penjamo"),
    "Guerrero": ("acapulco", "chilpancingo", "iguala", "zihuatanejo", "ixtapa", "taxco", "chilapa"),
    "Hidalgo": ("pachuca", "tulancingo", "tula", "tizayuca", "tula de allende", "mineral de la reforma",
                "ixmiquilpan", "huejutla"),
    "Jalisco": ("guadalajara", "zapopan", "tlaquepaque", "san pedro tlaquepaque", "tonala", "tlajomulco",
                "tlajomulco de zuniga", "puerto vallarta", "el salto", "lagos de moreno", "tepatitlan",
                "ocotlan", "chapala", "ajijic", "ciudad guzman", "zapotlan el grande"),
    "México": ("toluca", "ecatepec", "nezahualcoyotl", "neza", "naucalpan", "tlalnepantla", "chimalhuacan",
               "cuautitlan izcalli", "cuautitlan", "atizapan", "atizapan de zaragoza", "tultitlan", "ixtapaluca",
               "nicolas romero", "tecamac", "valle de chalco", "chalco", "coacalco", "huixquilucan", "texcoco",
               "metepec", "la paz edomex", "los reyes la paz", "zumpango", "lerma", "tenango", "tultepec",
               "melchor ocampo", "teoloyucan", "zinacantepec", "chicoloapan", "chiconcuac", "ciudad satelite",
               "interlomas"),
    "Michoacán": ("morelia", "uruapan", "zamora", "lazaro cardenas", "zitacuaro", "apatzingan", "patzcuaro",
                  "sahuayo", "la piedad", "hidalgo michoacan"),
    "Morelos": ("cuernavaca", "jiutepec", "cuautla", "temixco", "yautepec", "emiliano zapata", "tepoztlan",
                "xochitepec"),
    "Nayarit": ("tepic", "bahia de banderas", "nuevo vallarta", "san blas", "compostela", "xalisco"),
    "Nuevo León": ("monterrey", "san nicolas de los garza", "san nicolas", "guadalupe nl", "apodaca", "escobedo",
                   "general escobedo", "san pedro garza garcia", "san pedro garza", "santa catarina", "juarez nl",
                   "garcia", "cadereyta", "linares", "montemorelos", "santiago nl", "pesqueria", "salinas victoria"),
    "Oaxaca": ("oaxaca", "juchitan", "salina cruz", "tuxtepec", "huatulco", "puerto escondido", "santa cruz xoxocotlan"),
    "Puebla": ("puebla", "tehuacan", "san martin texmelucan", "atlixco", "cholula", "san pedro cholula",
               "san andres cholula", "huauchinango", "teziutlan", "amozoc", "cuautlancingo"),
    "Querétaro": ("queretaro", "san juan del rio", "corregidora", "el marques", "tequisquiapan", "juriquilla"),
    "Quintana Roo": ("cancun", "playa del carmen", "solidaridad", "chetumal", "cozumel", "tulum", "puerto morelos",
                     "isla mujeres", "bacalar", "felipe carrillo puerto"),
    "San Luis Potosí": ("san luis potosi", "soledad de graciano sanchez", "soledad", "ciudad valles", "matehuala",
                        "rioverde"),
    "Sinaloa": ("culiacan", "mazatlan", "los mochis", "ahome", "guasave", "navolato", "guamuchil", "el fuerte"),
    "Sonora": ("hermosillo", "ciudad obregon", "cd obregon", "cajeme", "nogales", "san luis rio colorado",
               "guaymas", "navojoa", "agua prieta", "puerto penasco", "caborca", "empalme"),
    "Tabasco": ("villahermosa", "cardenas", "comalcalco", "macuspana", "paraiso", "nacajuca", "centro tabasco"),
    "Tamaulipas": ("reynosa", "matamoros", "nuevo laredo", "tampico", "ciudad madero", "cd madero", "altamira",
                   "ciudad victoria", "cd victoria", "victoria tamaulipas", "rio bravo", "mante", "ciudad mante"),
    "Tlaxcala": ("tlaxcala", "apizaco", "huamantla", "chiautempan", "san pablo del monte", "zacatelco",
                 "calpulalpan"),
    "Veracruz": ("veracruz", "xalapa", "jalapa", "coatzacoalcos", "cordoba", "orizaba", "poza rica", "minatitlan",
                 "boca del rio", "tuxpan", "papantla", "san andres tuxtla", "martinez de la torre", "veracruz puerto"),
    "Yucatán": ("merida", "valladolid", "progreso", "kanasin", "tizimin", "uman", "ticul", "motul"),
    "Zacatecas": ("zacatecas", "fresnillo", "guadalupe zacatecas", "jerez", "rio grande"),
}

# Centros aproximados de municipios y ciudades grandes (además de las capitales de STATES) para deducir el
# estado por coordenadas: (estado, ciudad, latitud, longitud). Cubre las zonas metropolitanas que cruzan
# límites estatales (Valle de México, La Laguna, Puerto Vallarta / Bahía de Banderas, Tampico) y las ciudades
# lejos de su capital (Cancún, Ciudad Juárez, Tijuana...). Precisión de pocos km: es una aproximación.
CITY_COORDS: tuple[tuple[str, str, float, float], ...] = (
    ("Aguascalientes", "Jesús María", 21.9614, -102.3436),
    ("Baja California", "Tijuana", 32.5149, -117.0382), ("Baja California", "Ensenada", 31.8667, -116.5964),
    ("Baja California", "Tecate", 32.5725, -116.6264), ("Baja California", "Rosarito", 32.3606, -117.0453),
    ("Baja California", "San Quintín", 30.5600, -115.9400), ("Baja California", "San Felipe", 31.0256, -114.8403),
    ("Baja California Sur", "Cabo San Lucas", 22.8905, -109.9167),
    ("Baja California Sur", "San José del Cabo", 23.0597, -109.7006),
    ("Baja California Sur", "Ciudad Constitución", 25.0322, -111.6634),
    ("Baja California Sur", "Loreto", 26.0128, -111.3478), ("Baja California Sur", "Guerrero Negro", 27.9589, -114.0561),
    ("Campeche", "Ciudad del Carmen", 18.6492, -91.8222), ("Campeche", "Escárcega", 18.6097, -90.7456),
    ("Campeche", "Champotón", 19.3500, -90.7167),
    ("Chiapas", "Tapachula", 14.9056, -92.2633), ("Chiapas", "San Cristóbal de las Casas", 16.7370, -92.6376),
    ("Chiapas", "Comitán", 16.2510, -92.1342), ("Chiapas", "Palenque", 17.5097, -91.9824),
    ("Chihuahua", "Ciudad Juárez", 31.6904, -106.4245), ("Chihuahua", "Delicias", 28.1931, -105.4717),
    ("Chihuahua", "Cuauhtémoc", 28.4053, -106.8667), ("Chihuahua", "Hidalgo del Parral", 26.9316, -105.6662),
    ("Chihuahua", "Nuevo Casas Grandes", 30.4167, -107.9167),
    ("Ciudad de México", "Gustavo A. Madero", 19.4840, -99.1110), ("Ciudad de México", "Iztapalapa", 19.3574, -99.0671),
    ("Ciudad de México", "Coyoacán", 19.3467, -99.1617), ("Ciudad de México", "Álvaro Obregón", 19.3587, -99.2033),
    ("Ciudad de México", "Tlalpan", 19.2940, -99.1700), ("Ciudad de México", "Xochimilco", 19.2620, -99.1060),
    ("Ciudad de México", "Benito Juárez", 19.3727, -99.1564), ("Ciudad de México", "Miguel Hidalgo", 19.4280, -99.2000),
    ("Ciudad de México", "Azcapotzalco", 19.4869, -99.1844), ("Ciudad de México", "Iztacalco", 19.3953, -99.0975),
    ("Ciudad de México", "Venustiano Carranza", 19.4300, -99.0900), ("Ciudad de México", "Tláhuac", 19.2869, -99.0040),
    ("Ciudad de México", "La Magdalena Contreras", 19.3150, -99.2400),
    ("Ciudad de México", "Cuajimalpa", 19.3570, -99.2990), ("Ciudad de México", "Milpa Alta", 19.1920, -99.0230),
    ("Coahuila", "Torreón", 25.5428, -103.4068), ("Coahuila", "Monclova", 26.9067, -101.4206),
    ("Coahuila", "Piedras Negras", 28.7000, -100.5236), ("Coahuila", "Ciudad Acuña", 29.3242, -100.9317),
    ("Coahuila", "Ramos Arizpe", 25.5394, -100.9472), ("Coahuila", "Sabinas", 27.8558, -101.1194),
    ("Coahuila", "San Pedro", 25.7592, -102.9827), ("Coahuila", "Matamoros", 25.5283, -103.2283),
    ("Colima", "Manzanillo", 19.1138, -104.3385), ("Colima", "Tecomán", 18.9089, -103.8747),
    ("Colima", "Villa de Álvarez", 19.2667, -103.7372),
    ("Durango", "Gómez Palacio", 25.5611, -103.4983), ("Durango", "Lerdo", 25.5361, -103.5242),
    ("Durango", "Santiago Papasquiaro", 25.0436, -105.4189),
    ("Guanajuato", "León", 21.1250, -101.6860), ("Guanajuato", "Irapuato", 20.6767, -101.3563),
    ("Guanajuato", "Celaya", 20.5235, -100.8157), ("Guanajuato", "Salamanca", 20.5739, -101.1957),
    ("Guanajuato", "Silao", 20.9478, -101.4281), ("Guanajuato", "San Miguel de Allende", 20.9144, -100.7436),
    ("Guanajuato", "Dolores Hidalgo", 21.1561, -100.9325), ("Guanajuato", "Acámbaro", 20.0303, -100.7222),
    ("Guanajuato", "Pénjamo", 20.4311, -101.7222), ("Guanajuato", "San Francisco del Rincón", 21.0181, -101.8553),
    ("Guerrero", "Acapulco", 16.8531, -99.8237), ("Guerrero", "Iguala", 18.3448, -99.5397),
    ("Guerrero", "Zihuatanejo", 17.6417, -101.5517), ("Guerrero", "Taxco", 18.5564, -99.6050),
    ("Guerrero", "Chilapa", 17.5944, -99.1778), ("Guerrero", "Tlapa", 17.5456, -98.5764),
    ("Hidalgo", "Tulancingo", 20.0833, -98.3667), ("Hidalgo", "Tula de Allende", 20.0539, -99.3431),
    ("Hidalgo", "Tizayuca", 19.8333, -98.9833), ("Hidalgo", "Ixmiquilpan", 20.4833, -99.2167),
    ("Hidalgo", "Huejutla", 21.1408, -98.4192), ("Hidalgo", "Mineral de la Reforma", 20.0717, -98.6997),
    ("Jalisco", "Zapopan", 20.7214, -103.3918), ("Jalisco", "Tlaquepaque", 20.6409, -103.2934),
    ("Jalisco", "Tonalá", 20.6243, -103.2341), ("Jalisco", "Tlajomulco", 20.4736, -103.4469),
    ("Jalisco", "Puerto Vallarta", 20.6534, -105.2253), ("Jalisco", "Lagos de Moreno", 21.3564, -101.9297),
    ("Jalisco", "Tepatitlán", 20.8167, -102.7667), ("Jalisco", "Ocotlán", 20.3500, -102.7667),
    ("Jalisco", "Ciudad Guzmán", 19.7042, -103.4614), ("Jalisco", "Chapala", 20.2967, -103.1917),
    ("Jalisco", "El Salto", 20.5194, -103.1797), ("Jalisco", "Autlán", 19.7711, -104.3653),
    ("Jalisco", "Ameca", 20.5481, -104.0453), ("Jalisco", "Arandas", 20.7067, -102.3464),
    ("México", "Ecatepec", 19.6010, -99.0500), ("México", "Nezahualcóyotl", 19.4006, -98.9888),
    ("México", "Naucalpan", 19.4753, -99.2378), ("México", "Tlalnepantla", 19.5367, -99.1950),
    ("México", "Chimalhuacán", 19.4214, -98.9540), ("México", "Cuautitlán Izcalli", 19.6460, -99.2110),
    ("México", "Atizapán de Zaragoza", 19.5590, -99.2670), ("México", "Tultitlán", 19.6450, -99.1690),
    ("México", "Ixtapaluca", 19.3180, -98.8820), ("México", "Nicolás Romero", 19.6220, -99.3110),
    ("México", "Tecámac", 19.7130, -98.9680), ("México", "Valle de Chalco", 19.2930, -98.9380),
    ("México", "Chalco", 19.2640, -98.8970), ("México", "Coacalco", 19.6310, -99.1100),
    ("México", "Huixquilucan", 19.3610, -99.3500), ("México", "Texcoco", 19.5110, -98.8820),
    ("México", "Los Reyes La Paz", 19.3600, -98.9520), ("México", "Metepec", 19.2510, -99.6040),
    ("México", "Zinacantepec", 19.2830, -99.7330), ("México", "Zumpango", 19.7970, -99.0990),
    ("México", "Chicoloapan", 19.4160, -98.9020), ("México", "Tultepec", 19.6850, -99.1280),
    ("México", "Lerma", 19.2850, -99.5120), ("México", "Cuautitlán", 19.6700, -99.1790),
    ("Michoacán", "Uruapan", 19.4116, -102.0566), ("Michoacán", "Zamora", 19.9853, -102.2836),
    ("Michoacán", "Lázaro Cárdenas", 17.9583, -102.2000), ("Michoacán", "Zitácuaro", 19.4361, -100.3572),
    ("Michoacán", "Apatzingán", 19.0886, -102.3506), ("Michoacán", "Pátzcuaro", 19.5131, -101.6089),
    ("Michoacán", "Sahuayo", 20.0575, -102.7172), ("Michoacán", "La Piedad", 20.3428, -102.0306),
    ("Michoacán", "Ciudad Hidalgo", 19.6919, -100.5536),
    ("Morelos", "Jiutepec", 18.8814, -99.1772), ("Morelos", "Cuautla", 18.8121, -98.9542),
    ("Morelos", "Temixco", 18.8500, -99.2333), ("Morelos", "Yautepec", 18.8833, -99.0667),
    ("Morelos", "Jojutla", 18.6150, -99.1800),
    ("Nayarit", "Nuevo Vallarta", 20.6990, -105.2960), ("Nayarit", "Bucerías", 20.7558, -105.3336),
    ("Nayarit", "Compostela", 21.2333, -104.9000), ("Nayarit", "Santiago Ixcuintla", 21.8111, -105.2083),
    ("Nayarit", "Xalisco", 21.4436, -104.9014),
    ("Nuevo León", "Guadalupe", 25.6775, -100.2597), ("Nuevo León", "San Nicolás de los Garza", 25.7417, -100.3022),
    ("Nuevo León", "Apodaca", 25.7817, -100.1886), ("Nuevo León", "General Escobedo", 25.7972, -100.3333),
    ("Nuevo León", "Santa Catarina", 25.6733, -100.4581), ("Nuevo León", "San Pedro Garza García", 25.6573, -100.4029),
    ("Nuevo León", "García", 25.8100, -100.5900), ("Nuevo León", "Juárez", 25.6461, -100.0950),
    ("Nuevo León", "Cadereyta", 25.5833, -99.9833), ("Nuevo León", "Linares", 24.8597, -99.5672),
    ("Nuevo León", "Montemorelos", 25.1872, -99.8267), ("Nuevo León", "Sabinas Hidalgo", 26.5072, -100.1783),
    ("Oaxaca", "Juchitán", 16.4333, -95.0194), ("Oaxaca", "Salina Cruz", 16.1667, -95.2000),
    ("Oaxaca", "Tuxtepec", 18.0883, -96.1236), ("Oaxaca", "Huatulco", 15.7681, -96.1350),
    ("Oaxaca", "Puerto Escondido", 15.8667, -97.0667),
    ("Puebla", "Tehuacán", 18.4617, -97.3928), ("Puebla", "San Martín Texmelucan", 19.2833, -98.4333),
    ("Puebla", "Atlixco", 18.9000, -98.4333), ("Puebla", "San Pedro Cholula", 19.0631, -98.3069),
    ("Puebla", "Teziutlán", 19.8167, -97.3500), ("Puebla", "Huauchinango", 20.1750, -98.0528),
    ("Puebla", "Izúcar de Matamoros", 18.6000, -98.4667),
    ("Querétaro", "San Juan del Río", 20.3889, -99.9961), ("Querétaro", "Corregidora", 20.5330, -100.4430),
    ("Querétaro", "Tequisquiapan", 20.5206, -99.8919),
    ("Quintana Roo", "Cancún", 21.1619, -86.8515), ("Quintana Roo", "Playa del Carmen", 20.6296, -87.0739),
    ("Quintana Roo", "Cozumel", 20.5083, -86.9458), ("Quintana Roo", "Tulum", 20.2114, -87.4654),
    ("Quintana Roo", "Felipe Carrillo Puerto", 19.5800, -88.0453), ("Quintana Roo", "Bacalar", 18.6778, -88.3953),
    ("Quintana Roo", "Isla Mujeres", 21.2311, -86.7310), ("Quintana Roo", "Puerto Morelos", 20.8478, -86.8756),
    ("San Luis Potosí", "Soledad de Graciano Sánchez", 22.1833, -100.9333),
    ("San Luis Potosí", "Ciudad Valles", 21.9833, -99.0167), ("San Luis Potosí", "Matehuala", 23.6500, -100.6444),
    ("San Luis Potosí", "Rioverde", 21.9306, -99.9944),
    ("Sinaloa", "Mazatlán", 23.2494, -106.4111), ("Sinaloa", "Los Mochis", 25.7903, -108.9858),
    ("Sinaloa", "Guasave", 25.5667, -108.4667), ("Sinaloa", "Guamúchil", 25.4667, -108.0833),
    ("Sinaloa", "Navolato", 24.7650, -107.7019), ("Sinaloa", "Escuinapa", 22.8333, -105.7667),
    ("Sonora", "Ciudad Obregón", 27.4864, -109.9408), ("Sonora", "Nogales", 31.3086, -110.9422),
    ("Sonora", "San Luis Río Colorado", 32.4561, -114.7719), ("Sonora", "Guaymas", 27.9183, -110.8989),
    ("Sonora", "Navojoa", 27.0667, -109.4500), ("Sonora", "Agua Prieta", 31.3272, -109.5489),
    ("Sonora", "Puerto Peñasco", 31.3172, -113.5372), ("Sonora", "Caborca", 30.7167, -112.1500),
    ("Sonora", "Huatabampo", 26.8261, -109.6422),
    ("Tabasco", "Cárdenas", 18.0000, -93.3667), ("Tabasco", "Comalcalco", 18.2667, -93.2167),
    ("Tabasco", "Macuspana", 17.7667, -92.6000), ("Tabasco", "Paraíso", 18.3986, -93.2128),
    ("Tabasco", "Tenosique", 17.4744, -91.4231),
    ("Tamaulipas", "Reynosa", 26.0922, -98.2778), ("Tamaulipas", "Matamoros", 25.8697, -97.5028),
    ("Tamaulipas", "Nuevo Laredo", 27.4861, -99.5069), ("Tamaulipas", "Tampico", 22.2553, -97.8686),
    ("Tamaulipas", "Ciudad Madero", 22.2756, -97.8322), ("Tamaulipas", "Altamira", 22.3933, -97.9431),
    ("Tamaulipas", "Río Bravo", 25.9864, -98.0944), ("Tamaulipas", "El Mante", 22.7431, -98.9739),
    ("Tlaxcala", "Apizaco", 19.4167, -98.1333), ("Tlaxcala", "Huamantla", 19.3133, -97.9233),
    ("Tlaxcala", "Chiautempan", 19.3133, -98.1897), ("Tlaxcala", "Calpulalpan", 19.5869, -98.5694),
    ("Tlaxcala", "San Pablo del Monte", 19.1167, -98.1667), ("Tlaxcala", "Zacatelco", 19.2167, -98.2333),
    ("Veracruz", "Veracruz", 19.1738, -96.1342), ("Veracruz", "Boca del Río", 19.1056, -96.1053),
    ("Veracruz", "Coatzacoalcos", 18.1500, -94.4333), ("Veracruz", "Córdoba", 18.8833, -96.9333),
    ("Veracruz", "Orizaba", 18.8500, -97.1000), ("Veracruz", "Poza Rica", 20.5333, -97.4500),
    ("Veracruz", "Minatitlán", 17.9833, -94.5500), ("Veracruz", "Tuxpan", 20.9500, -97.4000),
    ("Veracruz", "Papantla", 20.4500, -97.3167), ("Veracruz", "San Andrés Tuxtla", 18.4483, -95.2131),
    ("Veracruz", "Martínez de la Torre", 20.0667, -97.0500), ("Veracruz", "Pánuco", 22.0500, -98.1833),
    ("Veracruz", "Tierra Blanca", 18.4500, -96.3500), ("Veracruz", "Acayucan", 17.9500, -94.9167),
    ("Yucatán", "Valladolid", 20.6894, -88.2017), ("Yucatán", "Progreso", 21.2833, -89.6667),
    ("Yucatán", "Kanasín", 20.9333, -89.5500), ("Yucatán", "Tizimín", 21.1428, -88.1653),
    ("Yucatán", "Umán", 20.8833, -89.7500), ("Yucatán", "Ticul", 20.4000, -89.5333),
    ("Yucatán", "Motul", 21.1000, -89.2833), ("Yucatán", "Tekax", 20.2000, -89.2833),
    ("Zacatecas", "Fresnillo", 23.1750, -102.8675), ("Zacatecas", "Guadalupe", 22.7472, -102.5181),
    ("Zacatecas", "Jerez", 22.6500, -103.0000), ("Zacatecas", "Río Grande", 23.8250, -103.0333),
    ("Zacatecas", "Sombrerete", 23.6333, -103.6333),
)

# Deducción por coordenadas (centro más cercano entre capitales y CITY_COORDS):
#  - más lejos que esto de todo centro conocido => None (zona rural sin referencia cercana)
MAX_CENTER_DISTANCE_KM = 150.0
#  - ambigüedad: si el centro más cercano de OTRO estado está casi igual de cerca, no se adivina (None).
#    "Casi igual" = la diferencia es menor que AMBIGUOUS_MIN_KM o que AMBIGUOUS_RATIO × la distancia menor.
AMBIGUOUS_MIN_KM = 2.0
AMBIGUOUS_RATIO = 0.35


def norm(text: str | None) -> str:
    """Minúsculas, sin acentos ni puntuación sobrante; espacios colapsados."""
    raw = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    raw = re.sub(r"[^a-z0-9.\s]", " ", raw)
    return " ".join(raw.split())


def _build_index() -> tuple[dict[str, str], dict[str, str]]:
    states: dict[str, str] = {}
    cities: dict[str, str] = {}
    for name, capital, _lat, _lon, aliases in STATES:
        states[norm(name)] = name
        for alias in aliases:
            states[norm(alias)] = name
            states[alias.lower()] = name  # con puntos ("n.l.", "d.f.")
        cities.setdefault(norm(capital), name)
    for state, names in CITIES.items():
        for city in names:
            cities.setdefault(norm(city), state)
    return states, cities


_STATE_INDEX, _CITY_INDEX = _build_index()
# El país al final ("Monterrey, Nuevo León, México") no es el Estado de México
COUNTRY_WORDS = {"mexico", "mx", "mex", "republica mexicana", "estados unidos mexicanos"}
# Dentro de un texto libre "méxico" suele ser el país ("León México", "Puebla, México"): no cuenta como estado
# (el Estado de México se reconoce por "estado de méxico", "edomex", "edo. de méx."...)
TEXT_IGNORED_ALIASES = {"mexico"}
_TRAILING_COUNTRY_RE = re.compile(r"\s+(?:mexico|mx|republica mexicana)\.?$")
# Dentro de un texto libre solo cuentan alias largos: "col", "sin", "son", "ver"... son palabras comunes
MIN_ALIAS_IN_TEXT = 6
# Separadores entre ciudad, estado y país ("Torreón, Coahuila" / "Zapopan / Jal." / "León - Gto")
_PARTS_RE = re.compile(r"[,/|;]|\s-\s")


def _split_parts(text: str | None) -> list[str]:
    """Tramos normalizados del texto (se separa antes de normalizar: norm() quita las comas)."""
    return [p for p in (norm(part) for part in _PARTS_RE.split(text or "")) if p]


def normalize_state(value: str | None) -> str | None:
    """Nombre oficial del estado a partir de lo que escribió la gente; None si no se reconoce."""
    key = norm(value)
    if not key:
        return None
    key = key.replace("estado de ", "", 1) if key.startswith("estado de ") and key != "estado de mexico" else key
    if key in _STATE_INDEX:
        return _STATE_INDEX[key]
    if key.rstrip(".") in _STATE_INDEX:
        return _STATE_INDEX[key.rstrip(".")]
    # "Coahuila de Zaragoza", "Veracruz, México"...: el primer tramo antes de la coma
    parts = _split_parts(value)
    if len(parts) > 1 and parts[0].rstrip(".") in _STATE_INDEX:
        return _STATE_INDEX[parts[0].rstrip(".")]
    return None


def state_for_city(city: str | None) -> str | None:
    """Estado al que pertenece una ciudad/municipio ("Torreón", "Torreón, Coahuila", "Zapopan, Jal.")."""
    parts = _split_parts(city)
    if not parts:
        return None
    while len(parts) > 1 and parts[-1].rstrip(".") in COUNTRY_WORDS:
        parts.pop()
    # "León México" / "Tijuana mx": el país pegado al final del último tramo tampoco cuenta
    stripped = _TRAILING_COUNTRY_RE.sub("", parts[-1]).strip()
    if stripped and stripped != parts[-1] and normalize_state(parts[-1]) is None:
        parts[-1] = stripped
    key = " ".join(parts)
    # Si el texto ya trae el estado ("Torreón, Coahuila" / "Cancún, Q. Roo") se toma ese
    for part in reversed(parts):
        found = normalize_state(part)
        if found:
            return found
    # Ciudad completa o alguno de sus tramos, del último al primero: lo más general va al final
    # ("Benito Juárez, Cancún" es el municipio de Cancún, no la alcaldía de la Ciudad de México)
    if key in _CITY_INDEX:
        return _CITY_INDEX[key]
    for part in reversed(parts):
        if part in _CITY_INDEX:
            return _CITY_INDEX[part]
    # Estado o ciudad mencionados dentro del texto: gana la coincidencia más larga
    # ("Ecatepec de Morelos" es del Estado de México, no de Morelos; "Dolores Hidalgo" es de Guanajuato)
    best, best_len = None, 0
    for alias, state in _STATE_INDEX.items():
        if alias in TEXT_IGNORED_ALIASES:
            continue
        if len(alias) >= MIN_ALIAS_IN_TEXT and len(alias) > best_len and re.search(rf"\b{re.escape(alias)}\b", key):
            best, best_len = state, len(alias)
    for name, state in _CITY_INDEX.items():
        if len(name) >= 5 and len(name) > best_len and re.search(rf"\b{re.escape(name)}\b", key):
            best, best_len = state, len(name)
    return best


# Centros conocidos para deducir el estado por coordenadas: capitales + municipios grandes
_CENTERS: tuple[tuple[str, float, float], ...] = tuple(
    [(name, lat, lon) for name, _capital, lat, lon, _aliases in STATES]
    + [(state, lat, lon) for state, _city, lat, lon in CITY_COORDS]
)


def state_for_coords(lat: float | None, lon: float | None) -> str | None:
    """Estado del centro conocido (capital o municipio grande) más cercano; None lejos de todos o si es ambiguo.

    Sin geocodificador: se compara con los centros de STATES y CITY_COORDS. Si el centro más cercano de otro
    estado queda casi a la misma distancia (zonas limítrofes), se devuelve None en lugar de adivinar: un estado
    equivocado haría leer los grupos de Facebook de otra zona.
    """
    if lat is None or lon is None:
        return None
    best: dict[str, float] = {}
    for state, clat, clon in _CENTERS:
        km = _haversine_km(lat, lon, clat, clon)
        if km < best.get(state, math.inf):
            best[state] = km
    ranked = sorted(best.items(), key=lambda item: item[1])
    if not ranked or ranked[0][1] > MAX_CENTER_DISTANCE_KM:
        return None
    state, d1 = ranked[0]
    d2 = ranked[1][1] if len(ranked) > 1 else math.inf
    if d2 - d1 < max(AMBIGUOUS_MIN_KM, d1 * AMBIGUOUS_RATIO):
        return None
    return state


def derive_state(state: str | None = None, city: str | None = None,
                 lat: float | None = None, lon: float | None = None) -> str | None:
    """Estado del reporte: lo que mandó la app (normalizado) > ciudad > coordenadas > None."""
    return normalize_state(state) or state_for_city(city) or state_for_coords(lat, lon)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))
