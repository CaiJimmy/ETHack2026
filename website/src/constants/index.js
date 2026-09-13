import { Globe2, Building2, ArrowUpRight } from 'lucide-react';

export const prompts = [
  { label: 'Find methane hotspots', question: 'Show the five largest methane plume observations in Texas during 2025.', icon: Globe2 },
  { label: 'Investigate target gaps', question: 'Which five utilities have the largest positive target gaps?', icon: Building2 },
  { label: 'Prepare company engagement', question: 'Compare XOM and CVX and suggest climate engagement questions.', icon: ArrowUpRight },
];

export const initialFilters = {
  gas: 'CH4',
  country: '',
  sector: '',
  start: '2025-01-01',
  end: '2025-12-31',
  minRate: ''
};

export const companyFiltersDefault = {
  sector: '',
  search: '',
  sort: 'gap',
  minGap: ''
};

export const sectorColors = {
  'Information Technology': '#487e85',
  'Financials': '#718359',
  'Communication Services': '#666a97',
  'Consumer Discretionary': '#a67b53',
  'Health Care': '#648eaa',
  'Industrials': '#8b9672',
  'Consumer Staples': '#b68c6a',
  'Energy': '#c57b47',
  'Utilities': '#719d78',
  'Materials': '#a0a563',
  'Real Estate': '#9382a0'
};
