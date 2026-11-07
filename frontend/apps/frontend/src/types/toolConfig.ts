import type { Attribute } from '@labels/interface';

export interface ToolsConfigState {
  tools: any[];
  tagList: any[];
  attributes: Attribute[];
  textConfig: any;
  commonAttributeConfigurable: boolean;
}
