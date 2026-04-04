// =============================================
// MOCK DATA
// =============================================
const mockProducts = [
  { id: '570824', title: 'Перчатки латексные нестерильные, 100 шт, р-р M', category: 'medical', categoryName: 'МЕДИЦИНА', status: 'Активна', attrs: ['Латекс', 'Нестерильные', 'Размер M', '100 шт'], price: 450, offers: 3, badges: ['frequent'] },
  { id: '570825', title: 'Шприц инъекционный одноразовый 5 мл', category: 'medical', categoryName: 'МЕДИЦИНА', status: 'Активна', attrs: ['5 мл', 'Стерильно', 'Игла 22G', '100 шт'], price: 120, offers: 5, badges: ['frequent'], historyCount: 2, historyDate: 'октябрь 2025' },
  { id: '570826', title: 'Бумага офисная А4, 500 листов, класс С', category: 'stationery', categoryName: 'КАНЦЕЛЯРИЯ', status: 'Активна', attrs: ['Формат А4', '80 г/м²', 'Класс С', 'Белая'], price: 280, offers: 12, badges: ['ai'] },
  { id: '570827', title: 'Мыло жидкое антибактериальное 5л', category: 'hardware', categoryName: 'ХОЗТОВАРЫ', status: 'Активна', attrs: ['Антибактериальное', 'Объем 5л', 'Пластиковая канистра'], price: 350, offers: 8, badges: ['seasonal'] },
  { id: '570828', title: 'Перчатки нитриловые нестерильные, 100 шт, р-р M', category: 'medical', categoryName: 'МЕДИЦИНА', status: 'Активна', attrs: ['Нитрил', 'Нестерильные', 'Размер M'], price: 520, offers: 4, badges: [] },
  { id: '570829', title: 'Перчатки виниловые, 100 шт, р-р M', category: 'medical', categoryName: 'МЕДИЦИНА', status: 'Активна', attrs: ['Винил', 'Нестерильные', 'Размер M'], price: 380, offers: 6, badges: [] },
  { id: '570830', title: 'Перчатки резиновые хозяйственные, пара', category: 'hardware', categoryName: 'ХОЗТОВАРЫ', status: 'Активна', attrs: ['Резина', 'Хозяйственные', 'Размер M'], price: 85, offers: 15, badges: [] },
  { id: '570831', title: 'Маски медицинские трёхслойные, 50 шт', category: 'medical', categoryName: 'МЕДИЦИНА', status: 'Активна', attrs: ['Трёхслойные', 'Стерильные', '50 шт'], price: 150, offers: 12, badges: ['frequent_together'] },
];

const togetherProducts = [
  { id: '570831', title: 'Маски медицинские трёхслойные, 50 шт', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Трёхслойные', '50 шт'], price: 150, offers: 12, badges: ['frequent_together'] },
  { id: '570832', title: 'Шприц инъекционный 10 мл с иглой', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['10 мл', '100 шт'], price: 180, offers: 7, badges: [] },
  { id: '570833', title: 'Бинт стерильный 5м × 10 см', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Стерильный', '5 м × 10 см'], price: 35, offers: 18, badges: [] },
  { id: '570834', title: 'Лейкопластырь бактерицидный, 100 шт', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Бактерицидный', '100 шт'], price: 90, offers: 9, badges: [] },
];

const analogProducts = [
  { id: '570835', title: 'Перчатки нитриловые ЭКОНОМ, 100 шт, р-р M', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Нитрил', 'Нестерильные'], price: 360, offers: 3, badges: ['cheaper'] },
  { id: '570836', title: 'Перчатки виниловые прозрачные, 100 шт', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Винил', 'Прозрачные'], price: 290, offers: 5, badges: ['cheaper'] },
  { id: '570837', title: 'Перчатки полиэтиленовые, 100 шт', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Полиэтилен', '100 шт'], price: 120, offers: 8, badges: ['cheaper'] },
];

const viewedProducts = [
  { id: '570826', title: 'Бумага офисная А4, 500 листов, класс С', category: 'stationery', categoryName: 'КАНЦЕЛЯРИЯ', attrs: ['Формат А4', '80 г/м²'], price: 280, offers: 12, badges: [] },
  { id: '570831', title: 'Маски медицинские трёхслойные, 50 шт', category: 'medical', categoryName: 'МЕДИЦИНА', attrs: ['Трёхслойные', '50 шт'], price: 150, offers: 12, badges: [] },
];

const categoryIcons = {
  medical: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
  stationery: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>',
  hardware: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  other: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>',
};

const badgeConfigs = {
  frequent: { cls: 'badge-frequent', icon: '<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>', label: 'Часто покупаете' },
  ai: { cls: 'badge-ai', icon: '<svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L9.09 8.26L2 9.27L7 14.14L5.82 21.02L12 17.77L18.18 21.02L17 14.14L22 9.27L14.91 8.26L12 2Z"/></svg>', label: 'AI рекомендует' },
  synonym: { cls: 'badge-synonym', icon: '', label: 'Синоним' },
  seasonal: { cls: 'badge-seasonal', icon: '❄', label: 'Сезонное' },
  frequent_together: { cls: 'badge-frequent-together', icon: '', label: 'Часто вместе' },
  cheaper: { cls: 'badge-cheaper', icon: '↓', label: 'Дешевле' },
};

const searchSuggestions = {
  history: ['бумага А4', 'шприц 5мл'],
  ai: ['перчатки латексные', 'маски медицинские', 'шприц инъекционный'],
};
