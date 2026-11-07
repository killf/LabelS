import styled from 'styled-components';
import { useTranslation } from '@labels/i18n';
import { FlexLayout } from '@labels/components-react';

import { ReactComponent as Logo } from '@/assets/svg/LOGO.svg';

const Description = styled.span`
  text-align: center;
  color: var(--color-text-secondary);
`;

const LogoTitle = () => {
  const { t } = useTranslation();
  return (
    <FlexLayout flex="column" items="center" gap="1rem">
      <Logo />
      <Description>
        <div>{t('labelSDescription')}</div>
        <div>{t('labelSKeywords')}</div>
      </Description>
    </FlexLayout>
  );
};
export default LogoTitle;
