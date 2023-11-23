

export const defaultMenu: menuItem[] = [
  {
    path: '',
    label: 'Home',
    access: ['Public'],
    children: [],
  },
  {
    path: 'wines',
    label: 'Wines',
    access: ['Admin'],
    children: [],
  },
  {
    path: 'comments',
    label: 'Comments',
    access: ['Admin', 'User'],
    children: [{    path: 'comments/add',
    label: 'CommentsAdd',
    access: ['Other'],
    children: [],}],
  },
  {
    path: 'profile',
    label: 'Profile',
    access: ['Admin', 'User'],
    children: [],
  },
];

export function getMenu(menu: menuItem[], accessGroup: String[]): menuItem[] {
  const result: menuItem[] = [];

  menu.forEach((item: menuItem) => {
    console.log(`${accessGroup} is include in ${item.label} with accessgroup ${item.access}: ${item.access.some(v => accessGroup.includes(v))}`)

    if (item.access.some(ag => accessGroup.includes(ag))) {
        const temp: menuItem={
            path: item.path,
            label: item.label,
            access: item.access,
            children: getMenu(item.children, accessGroup),
        };
      result.push(temp);
    }
  });
  return result;
}


export function hasMenuAccess(
  menu: menuItem[],
  path: string,
  accessGroup: string[]
) {
  for (let i = 0; i < menu.length; i++) {
    const index = path.indexOf('/', 0);
    if (index > 0) {
      const beginPath = path.substring(0, index);
      if (menu[i].path.indexOf(beginPath) == 0) {
        if (menu[i].access.some((ag) => accessGroup.includes(ag.toString())))
          return hasMenuAccess(menu[i].children, path.substring(index), accessGroup);
        else return false;
      }
    } else {
      //End of the path
      if (menu[i].path.indexOf(path) == 0) {
        {
          return menu[i].access.some((ag) => accessGroup.includes(ag.toString()));
        }
      }
    }
  }
}