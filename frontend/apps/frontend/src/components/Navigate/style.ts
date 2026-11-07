import styled from 'styled-components';
import { FlexLayout } from '@labels/components-react';

import { ReactComponent as Logo } from '@/assets/svg/LOGO.svg';

export const NavigationWrapper = styled(FlexLayout)`
  height: var(--header-height);
  border-bottom: solid var(--color-border-secondary) 1px;
  box-sizing: border-box;
`;

export const LabelSLogo = styled(Logo)`
  width: 120px;
  height: 32px;
`;
