interface ISiteMetadataResult {
  siteTitle: string;
  siteUrl: string;
  description: string;
  logo: string;
  navLinks: {
    name: string;
    url: string;
  }[];
}

const data: ISiteMetadataResult = {
  siteTitle: 'Runninan',
  siteUrl: 'https://yinan.me/running_page',
  logo: 'https://github.com/yinan-c.png',
  description: '',
  navLinks: [
    {
      name: 'Running',
      url: '/',
    },
    {
      name: 'Maps',
      url: '/map',
    },
    {
      name: 'Hiking',
      url: '/hiking',
    },
    {
      name: 'Tracks',
      url: '/tracks',
    },
    {
      name: 'About',
      url: 'https://github.com/yinan-c',
    },
  ],
};

export default data;
